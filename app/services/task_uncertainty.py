"""Safe resolution of tasks whose external write result is uncertain."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db import get_session
from ..models import AccountActionTask, CommentTask, PublishTask
from .task_events import add_task_event


UNCERTAIN_QUEUE_TYPES = frozenset({"publishes", "comments", "actions"})
_MODELS = {
    "publishes": PublishTask,
    "comments": CommentTask,
    "actions": AccountActionTask,
}


class UncertainVerificationError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def automatic_uncertain_evidence(row: Any, queue_type: str) -> dict[str, Any]:
    """Return only evidence strong enough to mark a task done without re-writing."""
    queue_type = str(queue_type or "").strip().lower()
    evidence: dict[str, Any] = {"confirmed": False, "source": "none"}
    if queue_type != "publishes":
        return evidence

    result_id = str(getattr(row, "platform_result_id", "") or "").strip()
    result_url = str(getattr(row, "result_url", "") or "").strip()
    if result_id:
        return {
            "confirmed": True,
            "source": "stored_platform_result_id",
            "result_id": result_id,
            "result_url": result_url,
        }

    if getattr(row, "platform", "") == "youtube" and getattr(row, "id", None):
        try:
            from ..platforms.youtube.client import load
            record = load("upload_" + str(row.id))
        except Exception:
            record = {}
        video_id = str(record.get("video_id") or "").strip()
        if video_id:
            return {
                "confirmed": True,
                "source": "youtube_resumable_record",
                "result_id": video_id,
                "result_url": "https://www.youtube.com/watch?v=" + video_id,
            }
    return evidence


def apply_uncertain_resolution(row: Any, queue_type: str, resolution: str, *,
                               evidence: dict[str, Any] | None = None,
                               note: str = "") -> Any:
    queue_type = str(queue_type or "").strip().lower()
    resolution = str(resolution or "").strip().lower()
    if queue_type not in UNCERTAIN_QUEUE_TYPES:
        raise UncertainVerificationError("该队列类型不支持 uncertain 核验")
    if str(getattr(row, "status", "") or "").lower() != "uncertain":
        raise UncertainVerificationError("任务当前不是 uncertain 状态")
    if resolution not in {"confirmed_done", "confirmed_not_done"}:
        raise UncertainVerificationError("未知 uncertain 核验结论")

    now = _utcnow_naive()
    if resolution == "confirmed_done":
        row.status = "done"
        row.error = ""
        if hasattr(row, "done_at"):
            row.done_at = now
        if queue_type == "publishes":
            evidence = evidence or {}
            result_id = str(evidence.get("result_id") or "").strip()
            result_url = str(evidence.get("result_url") or "").strip()
            if result_id:
                row.platform_result_id = result_id
            if result_url:
                row.result_url = result_url
            row.source_revision += 1
        elif hasattr(row, "result") and not getattr(row, "result", ""):
            row.result = "verified"
    else:
        row.status = "failed"
        row.error = ("uncertain 核验确认未成功" + (f"：{note.strip()}" if note.strip() else ""))[:1000]
        if hasattr(row, "done_at"):
            row.done_at = None
        if queue_type == "publishes":
            row.source_revision += 1

    if hasattr(row, "scheduled_at"):
        row.scheduled_at = None
    for name, value in (
        ("blocked_reason", ""), ("blocked_signal", ""),
        ("blocked_operation", ""), ("blocked_at", None),
        ("next_allowed_at", None),
    ):
        if hasattr(row, name):
            setattr(row, name, value)
    return row


def verify_uncertain(queue_type: str, row_id: int, resolution: str,
                     *, note: str = "") -> dict[str, Any]:
    queue_type = str(queue_type or "").strip().lower()
    model = _MODELS.get(queue_type)
    if model is None:
        raise UncertainVerificationError("该队列类型不支持 uncertain 核验")

    with get_session() as session:
        row = session.get(model, row_id)
        if row is None:
            raise UncertainVerificationError("任务不存在", 404)
        if str(row.status or "").lower() != "uncertain":
            raise UncertainVerificationError("任务当前不是 uncertain 状态")

        evidence = automatic_uncertain_evidence(row, queue_type)
        requested = str(resolution or "").strip().lower()
        if requested == "auto":
            if not evidence.get("confirmed"):
                return {
                    "ok": True, "confirmed": False,
                    "queue_type": queue_type, "id": row_id,
                    "status": "uncertain", "evidence": evidence,
                }
            requested = "confirmed_done"
        before_status = str(row.status or "")
        apply_uncertain_resolution(
            row, queue_type, requested, evidence=evidence, note=note)
        session.add(row)
        add_task_event(
            session, queue_type=queue_type, row_id=row_id,
            event_type=f"uncertain:{requested}",
            from_status=before_status, to_status=str(row.status or ""),
            actor="task_queue",
            detail=note,
            metadata={"evidence": evidence},
        )
        session.commit()
        session.refresh(row)
        return {
            "ok": True, "confirmed": True,
            "queue_type": queue_type, "id": row_id,
            "status": row.status, "resolution": requested,
            "evidence": evidence,
        }
