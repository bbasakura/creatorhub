"""Unified control actions for the task-queue view.

This fork extension deliberately reuses existing models and MonitorEngine
execution methods.  It does not introduce a second scheduler or replace the
upstream worker state machines.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db import get_session
from ..models import (
    AccountActionTask,
    CommentTask,
    KeywordCollectionJob,
    PublishTask,
)
from .task_events import add_task_event
from .task_uncertainty import UncertainVerificationError, verify_uncertain


ACTIONABLE_QUEUE_TYPES = frozenset({"collections", "publishes", "comments", "actions"})
_QUEUE_MODELS = {
    "collections": KeywordCollectionJob,
    "publishes": PublishTask,
    "comments": CommentTask,
    "actions": AccountActionTask,
}
_RUNNING_STATUS = {
    "collections": "running",
    "publishes": "publishing",
    "comments": "doing",
    "actions": "doing",
}
_RETRYABLE_STATUS = {
    "collections": frozenset({"failed", "partial", "canceled"}),
    "publishes": frozenset({"failed", "canceled"}),
    "comments": frozenset({"failed", "canceled"}),
    "actions": frozenset({"failed", "canceled"}),
}
_UNCERTAIN_ACTIONS = {
    "verify-auto": "auto",
    "confirm-done": "confirmed_done",
    "confirm-not-done": "confirmed_not_done",
}


class QueueActionError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_blocked(row: Any) -> bool:
    return bool(
        str(getattr(row, "blocked_reason", "") or "").strip()
        or getattr(row, "next_allowed_at", None)
    )


def _clear_block(row: Any) -> None:
    for name, value in (
        ("blocked_reason", ""),
        ("blocked_signal", ""),
        ("blocked_operation", ""),
        ("blocked_at", None),
        ("next_allowed_at", None),
    ):
        if hasattr(row, name):
            setattr(row, name, value)


def available_queue_actions(queue_type: str, status: str, *,
                            blocked_reason: str = "",
                            next_allowed_at: datetime | None = None) -> list[str]:
    queue_type = str(queue_type or "").strip().lower()
    status = str(status or "").strip().lower()
    if queue_type not in ACTIONABLE_QUEUE_TYPES:
        return []
    running = _RUNNING_STATUS[queue_type]
    if status == "done":
        return []
    if status == "uncertain":
        return (["verify-auto", "confirm-done", "confirm-not-done"]
                if queue_type in {"publishes", "comments", "actions"} else [])
    if status == running:
        return ["cancel"] if queue_type == "collections" else []
    blocked = bool(str(blocked_reason or "").strip() or next_allowed_at)
    actions: list[str] = []
    if blocked:
        actions.append("resume")
    elif status in _RETRYABLE_STATUS[queue_type]:
        actions.append("retry")
    elif status in {"pending", "draft"}:
        actions.append("run-now")
    if status in {"pending", "draft"}:
        actions.append("cancel")
    return actions


def apply_queue_transition(row: Any, queue_type: str, action: str,
                           *, now: datetime | None = None) -> Any:
    """Apply a local state transition without executing external platform I/O."""
    queue_type = str(queue_type or "").strip().lower()
    action = str(action or "").strip().lower()
    if queue_type not in ACTIONABLE_QUEUE_TYPES:
        raise QueueActionError("该队列类型不支持控制操作", 400)
    if action not in {"run-now", "cancel", "retry", "resume"}:
        raise QueueActionError("未知任务操作", 400)
    current = str(getattr(row, "status", "") or "").lower()
    running = _RUNNING_STATUS[queue_type]
    now = now or _utcnow_naive()

    if action == "cancel":
        if queue_type == "collections":
            if current not in {"pending", "running"}:
                raise QueueActionError(f"任务状态为 {current}，不可取消")
            row.cancel_requested = True
            if current == "pending":
                row.status = "canceled"
                row.current_step = "已取消"
                row.finished_at = now
            else:
                row.current_step = "正在安全停止"
            return row
        if current in {running, "done", "uncertain"}:
            raise QueueActionError(f"任务状态为 {current}，不可取消")
        row.status = "canceled"
        if hasattr(row, "scheduled_at"):
            row.scheduled_at = None
        _clear_block(row)
        return row

    if action == "retry":
        if current not in _RETRYABLE_STATUS[queue_type]:
            raise QueueActionError(f"任务状态为 {current}，不可重试")
        if queue_type == "collections":
            row.status = "pending"
            row.current_keyword = ""
            row.current_step = "等待继续"
            row.error_count = 0
            row.error = ""
            row.cancel_requested = False
            row.started_at = None
            row.finished_at = None
            _clear_block(row)
            return row
        row.status = "pending"
        row.error = ""
        if hasattr(row, "scheduled_at"):
            row.scheduled_at = None
        if hasattr(row, "done_at"):
            row.done_at = None
        _clear_block(row)
        return row

    if action == "resume":
        if current in {running, "done", "uncertain"} or not _is_blocked(row):
            raise QueueActionError("该任务当前没有可解除的阻塞状态")
        row.status = "pending"
        row.error = ""
        if hasattr(row, "scheduled_at"):
            row.scheduled_at = None
        if queue_type == "collections":
            row.cancel_requested = False
            row.current_step = "等待继续"
            row.finished_at = None
        _clear_block(row)
        return row

    # run-now: normalize to pending first, then caller delegates to the existing worker.
    if current in {running, "done", "uncertain"}:
        raise QueueActionError(f"任务状态为 {current}，不可立即执行")
    row.status = "pending"
    row.error = ""
    if hasattr(row, "scheduled_at"):
        row.scheduled_at = None
    if hasattr(row, "done_at"):
        row.done_at = None
    if queue_type == "collections":
        row.cancel_requested = False
        row.current_step = "等待执行"
        row.finished_at = None
    _clear_block(row)
    return row


def _load_and_transition(queue_type: str, row_id: int, action: str) -> Any:
    model = _QUEUE_MODELS.get(queue_type)
    if model is None:
        raise QueueActionError("该队列类型不支持控制操作")
    with get_session() as session:
        row = session.get(model, row_id)
        if row is None:
            raise QueueActionError("任务不存在", 404)
        before_status = str(getattr(row, "status", "") or "")
        apply_queue_transition(row, queue_type, action)
        session.add(row)
        add_task_event(
            session, queue_type=queue_type, row_id=row_id,
            event_type=f"control:{action}",
            from_status=before_status,
            to_status=str(getattr(row, "status", "") or ""),
            actor="task_queue",
        )
        session.commit()
        session.refresh(row)
        return row


def _result(queue_type: str, row: Any, action: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "ok": True,
        "queue_type": queue_type,
        "id": row.id,
        "action": action,
        "status": row.status,
    }
    payload.update(extra)
    return payload


async def perform_queue_action(queue_type: str, row_id: int, action: str,
                               *, engine: Any = None) -> dict[str, Any]:
    queue_type = str(queue_type or "").strip().lower()
    action = str(action or "").strip().lower()
    if action in _UNCERTAIN_ACTIONS:
        try:
            return verify_uncertain(queue_type, row_id, _UNCERTAIN_ACTIONS[action])
        except UncertainVerificationError as exc:
            raise QueueActionError(str(exc), exc.status_code) from exc
    if action == "run-now" and engine is None:
        raise QueueActionError("引擎未就绪", 503)

    row = _load_and_transition(queue_type, row_id, action)

    if action in {"retry", "resume"}:
        queued = None
        if queue_type == "collections" and engine is not None:
            queued = bool(engine.enqueue_collection_job(row_id))
        return _result(queue_type, row, action, queued=queued)
    if action == "cancel":
        return _result(queue_type, row, action)

    if queue_type == "collections":
        queued = bool(engine.enqueue_collection_job(row_id))
        return _result(queue_type, row, action, queued=queued)
    if queue_type == "publishes":
        outcome = await engine.publish_task(row_id, manual=True)
    elif queue_type == "comments":
        outcome = await engine.execute_comment_task(row_id)
    elif queue_type == "actions":
        outcome = await engine.execute_action_task(row_id)
    else:
        raise QueueActionError("该队列类型不支持立即执行")
    if not outcome.get("ok"):
        raise QueueActionError(outcome.get("error") or "任务执行失败")
    return _result(queue_type, row, action, outcome=outcome)
