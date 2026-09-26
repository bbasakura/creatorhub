"""Task event timeline helpers for control-plane auditing."""
from __future__ import annotations

import json
from typing import Any

from sqlmodel import select

from ..db import get_session
from ..models import TaskEvent


def add_task_event(session: Any, *, queue_type: str, row_id: int,
                   event_type: str, from_status: str = "", to_status: str = "",
                   actor: str = "system", detail: str = "",
                   metadata: dict[str, Any] | None = None) -> TaskEvent:
    event = TaskEvent(
        queue_type=str(queue_type or "").strip().lower(),
        row_id=int(row_id),
        event_type=str(event_type or "").strip()[:80],
        from_status=str(from_status or "").strip()[:40],
        to_status=str(to_status or "").strip()[:40],
        actor=str(actor or "system").strip()[:80],
        detail=str(detail or "").strip()[:1000],
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
    )
    session.add(event)
    return event


def task_event_dict(event: TaskEvent) -> dict[str, Any]:
    try:
        metadata = json.loads(event.metadata_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    return {
        "id": event.id,
        "queue_type": event.queue_type,
        "row_id": event.row_id,
        "event_type": event.event_type,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "actor": event.actor,
        "detail": event.detail,
        "metadata": metadata,
        "created_at": event.created_at.isoformat() + "Z" if event.created_at else None,
    }


def list_task_events(queue_type: str, row_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(500, int(limit)))
    with get_session() as session:
        rows = session.exec(
            select(TaskEvent)
            .where(TaskEvent.queue_type == str(queue_type or "").strip().lower())
            .where(TaskEvent.row_id == int(row_id))
            .order_by(TaskEvent.id.desc())
            .limit(limit)
        ).all()
        return [task_event_dict(row) for row in rows]
