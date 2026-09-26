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
