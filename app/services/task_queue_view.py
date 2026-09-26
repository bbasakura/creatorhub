"""Pure normalization helpers for the unified task-queue API."""
from __future__ import annotations

import json
from datetime import datetime, timezone

QUEUE_TYPES = {
    "collections", "publishes", "comments", "actions",
    "monitor_downloads", "collection_downloads",
}
QUEUE_STATES = {"active", "pending", "running", "blocked", "failed", "completed", "all"}
QUEUE_RUNNING = {"running", "publishing", "doing", "downloading"}
QUEUE_FAILED = {"failed", "partial", "uncertain"}
QUEUE_COMPLETED = {"done", "canceled", "skipped"}


def queue_iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") + "Z" if value else None


def queue_state(status: str, *, blocked_reason: str = "",
                next_allowed_at: datetime | None = None) -> str:
    status = str(status or "").lower()
    if status in QUEUE_FAILED:
        return "failed"
    if status in QUEUE_COMPLETED:
        return "completed"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if blocked_reason or (next_allowed_at and next_allowed_at > now):
        return "blocked"
    if status in QUEUE_RUNNING:
        return "running"
    return "pending"


def queue_keywords(value: str) -> str:
    try:
        values = json.loads(value or "[]")
    except (TypeError, ValueError):
        values = []
    if isinstance(values, list):
        text = "、".join(str(item).strip() for item in values if str(item).strip())
        if text:
            return text
    return str(value or "").strip() or "未命名关键词任务"
