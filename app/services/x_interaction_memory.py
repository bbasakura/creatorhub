"""Read-only interaction memory for X reply decisions.

The durable CommentTask table is already the source of truth for replies.  This
service derives compact per-handle context from successful X replies instead of
adding another persistence model or a second source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import select

from ..db import get_session
from ..models import CommentTask


@dataclass(frozen=True)
class XInteractionMemory:
    handle: str
    successful_replies: int
    recent: tuple[dict, ...]

    def prompt_context(self, *, max_chars: int = 1800) -> str:
        if not self.recent:
            return ""
        lines = [
            f"与 @{self.handle} 历史成功互动 {self.successful_replies} 次。",
            "最近互动：",
        ]
        for item in self.recent:
            source = str(item.get("source_text") or "").strip()
            reply = str(item.get("reply") or "").strip()
            if source:
                lines.append(f"- 对方：{source}")
            if reply:
                lines.append(f"  我方：{reply}")
        return "\n".join(lines)[:max_chars]


def load_x_interaction_memory(account_id: int, author_handle: str, *, limit: int = 6) -> XInteractionMemory:
    handle = str(author_handle or "").strip().lstrip("@").casefold()
    if not handle:
        return XInteractionMemory(handle="", successful_replies=0, recent=())
    safe_limit = max(1, min(20, int(limit or 6)))
    with get_session() as session:
        query = (
            select(CommentTask)
            .where(
                CommentTask.platform == "x",
                CommentTask.account_id == int(account_id),
                CommentTask.status == "done",
                func.lower(CommentTask.target_nick) == handle,
            )
            .order_by(CommentTask.done_at.desc(), CommentTask.created_at.desc())
        )
        rows = session.exec(query).all()
    recent = tuple({
        "tweet_id": str(row.aweme_id or ""),
        "source_text": str(row.target_text or "")[:240],
        "reply": str(row.content or "")[:280],
        "done_at": row.done_at.isoformat() if row.done_at else "",
    } for row in rows[:safe_limit])
    return XInteractionMemory(
        handle=handle,
        successful_replies=len(rows),
        recent=recent,
    )
