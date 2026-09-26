"""Persistence guard for idempotent direct-publish task creation."""
from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from ..models import PublishTask


class PublishIntentConflict(RuntimeError):
    pass


def _existing(session: Any, intent_key: str | None) -> PublishTask | None:
    if not intent_key:
        return None
    return session.exec(select(PublishTask).where(
        PublishTask.source_intent_key == intent_key)).first()


def _resolve_existing(existing: PublishTask, task: PublishTask,
                      *, explicit_intent: bool) -> tuple[PublishTask, bool]:
    if existing.content_fingerprint != task.content_fingerprint:
        raise PublishIntentConflict(
            "intent_id 已被另一份发布内容占用，请更换 intent_id")
    if explicit_intent:
        return existing, True
    raise PublishIntentConflict(
        f"相同发布意图已有任务 #{existing.id}，请使用原任务重试；"
        "确需重复发布请显式允许重复")


def persist_direct_publish(session: Any, task: PublishTask, *,
                           explicit_intent: bool = False) -> tuple[PublishTask, bool]:
    """Insert once; concurrent duplicate inserts converge on the existing row."""
    existing = _existing(session, task.source_intent_key)
    if existing is not None:
        return _resolve_existing(existing, task, explicit_intent=explicit_intent)

    session.add(task)
    try:
        session.commit()
        session.refresh(task)
        return task, False
    except IntegrityError:
        session.rollback()
        existing = _existing(session, task.source_intent_key)
        if existing is None:
            raise
        return _resolve_existing(existing, task, explicit_intent=explicit_intent)


def refresh_direct_publish_identity(session: Any, task: PublishTask,
                                    fingerprint: str) -> bool:
    """Refresh editable direct-publish identity without touching source-owned keys."""
    fingerprint = str(fingerprint or "").strip()
    if not fingerprint:
        raise ValueError("fingerprint 不能为空")

    key = str(task.source_intent_key or "")
    is_direct = not (task.source_platform or "").strip() or key.startswith("publish:")
    if not is_direct:
        task.source_revision += 1
        return False

    if ":client:" in key:
        if task.content_fingerprint and task.content_fingerprint != fingerprint:
            raise PublishIntentConflict(
                "显式 intent_id 任务不可修改发布语义；请用新的 intent_id 新建任务")
        task.content_fingerprint = fingerprint
        return False

    new_key = None
    if key.startswith("publish:") and ":fp:" in key:
        new_key = f"publish:{task.account_id}:fp:{fingerprint}"
        existing = _existing(session, new_key)
        if existing is not None and existing.id != task.id:
            raise PublishIntentConflict(
                f"编辑后的发布意图与任务 #{existing.id} 重复，请使用原任务")

    changed = (task.content_fingerprint != fingerprint
               or (new_key is not None and task.source_intent_key != new_key))
    task.content_fingerprint = fingerprint
    if new_key is not None:
        task.source_intent_key = new_key
    if changed:
        task.source_revision += 1
    return changed
