from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from ..models import AccountActionTask, XRelationshipBatch

_TERMINAL_TASK_STATES = {"done", "failed", "uncertain", "canceled"}


def relationship_batch_counts(session: Session, batch_id: int) -> dict[str, int]:
    rows = session.exec(select(AccountActionTask.status).where(
        AccountActionTask.batch_id == batch_id)).all()
    counts = {"pending": 0, "doing": 0, "done": 0, "failed": 0,
              "uncertain": 0, "canceled": 0}
    for status in rows:
        key = str(status or "")
        counts[key] = counts.get(key, 0) + 1
    counts["processed"] = sum(counts.get(key, 0)
                              for key in {"done", "failed", "uncertain", "canceled"})
    counts["total"] = len(rows)
    return counts


def refresh_relationship_batch(session: Session, batch: XRelationshipBatch | None,
                               *, now: datetime | None = None) -> XRelationshipBatch | None:
    if batch is None:
        return None
    counts = relationship_batch_counts(session, int(batch.id or 0))
    current = now or datetime.utcnow()
    batch.total_count = counts["total"]
    if batch.status != "canceled" and counts["total"] > 0 and counts["processed"] >= counts["total"]:
        batch.status = "completed"
        batch.done_at = batch.done_at or current
    elif batch.status == "completed" and counts["processed"] < counts["total"]:
        batch.status = "active"
        batch.done_at = None
    batch.updated_at = current
    session.add(batch)
    return batch


def relationship_batch_dict(session: Session, batch: XRelationshipBatch) -> dict[str, Any]:
    refresh_relationship_batch(session, batch)
    counts = relationship_batch_counts(session, int(batch.id or 0))
    total = counts["total"]
    processed = counts["processed"]
    return {
        "id": batch.id, "platform": batch.platform, "account_id": batch.account_id,
        "action": batch.action, "status": batch.status,
        "requested_count": batch.requested_count, "total_count": total,
        "skipped_count": batch.skipped_count, "pending_count": counts["pending"],
        "doing_count": counts["doing"], "done_count": counts["done"],
        "failed_count": counts["failed"], "uncertain_count": counts["uncertain"],
        "canceled_count": counts["canceled"], "processed_count": processed,
        "progress": 100 if total == 0 else round(processed * 100 / total),
        "pause_reason": batch.pause_reason, "stop_signal": batch.stop_signal,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
        "done_at": batch.done_at.isoformat() if batch.done_at else None,
    }


def should_pause_relationship_batch(*, error: str = "", uncertain: bool = False,
                                    failure_category: str = "",
                                    failure_signal: str = "") -> tuple[bool, str, str]:
    if uncertain:
        return True, "出现结果不确定的 X 关系操作，批次已自动暂停", "uncertain"
    category = str(failure_category or "").casefold()
    signal = str(failure_signal or "").strip()
    if category in {"risk", "auth"}:
        return True, str(error or "").strip() or f"{category} 风险信号", signal or category
    text = str(error or "").casefold()
    for marker, marker_signal in (
        ("captcha", "captcha"), ("验证码", "captcha"), ("429", "rate_limit"),
        ("rate limit", "rate_limit"), ("too many requests", "rate_limit"),
        ("登录", "auth"), ("login", "auth"), ("restricted", "restriction"),
        ("restriction", "restriction"), ("限制", "restriction"),
        ("suspended", "restriction"), ("locked", "restriction"),
        ("verify", "verification"), ("验证", "verification"),
    ):
        if marker in text:
            return True, str(error or "").strip() or marker, signal or marker_signal
    return False, "", ""


def pause_relationship_batch(session: Session, batch_id: int | None, *,
                             reason: str, signal: str = "",
                             now: datetime | None = None) -> XRelationshipBatch | None:
    if not batch_id:
        return None
    batch = session.get(XRelationshipBatch, batch_id)
    if not batch or batch.status in {"canceled", "completed"}:
        return batch
    batch.status = "paused"
    batch.pause_reason = str(reason or "异常自动暂停")[:1000]
    batch.stop_signal = str(signal or "")[:120]
    batch.updated_at = now or datetime.utcnow()
    session.add(batch)
    return batch
