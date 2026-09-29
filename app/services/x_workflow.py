"""Durable X draft/approval workflow helpers.

Automation may discover/generate candidates freely, but external writes enter
CreatorHub's existing durable queues first.  Approval is the existing
``task-queue/.../run-now`` transition from ``draft`` to the authoritative
worker; this module does not create a second executor.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

from sqlmodel import select

from ..db import get_session
from ..models import CommentTask, PublishTask
from ..platforms.x.client import compose_x_text, normalize_tweet_ref
from .task_events import add_task_event


def _post_fingerprint(account_id: int, text: str, topics: str,
                      media_paths: Sequence[str]) -> str:
    payload = {
        "account_id": int(account_id),
        "text": str(text or "").strip(),
        "topics": str(topics or "").strip(),
        "media_paths": [str(Path(path)) for path in media_paths],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def create_x_post_draft(account_id: int, text: str, *, topics: str = "",
                        media_paths: Sequence[str] = (),
                        intent_id: str | None = None) -> dict:
    paths = [str(Path(path)) for path in media_paths if str(path or "").strip()]
    if len(paths) > 4:
        raise ValueError("X 单条帖子最多附加 4 个媒体文件")
    if any(not Path(path).is_file() for path in paths):
        raise ValueError("X 草稿媒体文件不存在")
    compose_x_text("", text, topics, allow_empty=bool(paths))
    fingerprint = _post_fingerprint(account_id, text, topics, paths)
    if intent_id:
        key = f"x-draft:{account_id}:client:{intent_id}"
    else:
        key = f"x-draft:{account_id}:fp:{fingerprint}"

    with get_session() as session:
        existing = session.exec(select(PublishTask).where(
            PublishTask.source_intent_key == key)).first()
        if existing is not None:
            if existing.content_fingerprint != fingerprint:
                raise ValueError("intent_id 已用于不同的 X 草稿内容")
            return {
                "ok": True, "draft": True, "idempotent_replay": True,
                "queue_type": "publishes", "task_id": existing.id,
                "status": existing.status,
            }

        task = PublishTask(
            platform="x", account_id=account_id,
            media_type="media" if paths else "text",
            title="", desc=str(text or "").strip(), topics=str(topics or "").strip(),
            media_json=json.dumps(paths, ensure_ascii=False),
            visibility="public", operation="publish", status="draft",
            content_fingerprint=fingerprint, source_intent_key=key,
        )
        session.add(task)
        session.flush()
        add_task_event(
            session, queue_type="publishes", row_id=task.id,
            event_type="draft:created", from_status="", to_status="draft",
            actor="x_workflow", detail="X 发帖草稿已创建，等待人工审核/执行")
        session.commit()
        session.refresh(task)
        return {
            "ok": True, "draft": True, "idempotent_replay": False,
            "queue_type": "publishes", "task_id": task.id,
            "status": task.status,
        }


def create_x_reply_draft(account_id: int, tweet_ref: str, text: str, *,
                         author_handle: str = "", source_text: str = "") -> dict:
    reply = str(text or "").strip()
    if not reply:
        raise ValueError("X 回复内容不能为空")
    if len(reply) > 280:
        raise ValueError("X 回复超过 280 字符")
    tweet_id, canonical_url = normalize_tweet_ref(tweet_ref)

    with get_session() as session:
        rows = session.exec(select(CommentTask).where(
            CommentTask.platform == "x",
            CommentTask.account_id == account_id,
            CommentTask.aweme_id == tweet_id,
            CommentTask.content == reply,
        )).all()
        existing = next((row for row in rows if row.status not in {"failed", "canceled"}), None)
        if existing is not None:
            return {
                "ok": True, "draft": existing.status == "draft",
                "idempotent_replay": True, "queue_type": "comments",
                "task_id": existing.id, "status": existing.status,
                "tweet_id": tweet_id, "url": canonical_url,
            }

        task = CommentTask(
            platform="x", account_id=account_id,
            aweme_id=tweet_id, target_comment_id=tweet_id,
            target_nick=str(author_handle or "").strip().lstrip("@")[:100],
            target_text=str(source_text or "")[:200],
            content=reply, status="draft", method="browser",
        )
        session.add(task)
        session.flush()
        add_task_event(
            session, queue_type="comments", row_id=task.id,
            event_type="draft:created", from_status="", to_status="draft",
            actor="x_workflow",
            detail=f"X 回复草稿已创建，目标 tweet={tweet_id}，等待人工审核/执行")
        session.commit()
        session.refresh(task)
        return {
            "ok": True, "draft": True, "idempotent_replay": False,
            "queue_type": "comments", "task_id": task.id,
            "status": task.status, "tweet_id": tweet_id, "url": canonical_url,
        }
