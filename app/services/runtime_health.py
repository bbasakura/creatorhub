"""CreatorHub liveness/readiness diagnostics.

`/health` remains a cheap liveness probe.  This module builds the stronger
readiness view used to decide whether the single in-process executor can safely
accept/execute work.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import select

from ..db import get_session
from ..models import (
    AccountActionTask,
    CommentTask,
    KeywordCollectionJob,
    PublishTask,
)


_QUEUE_SPECS = (
    ("publishes", PublishTask, "pending", "publishing"),
    ("comments", CommentTask, "pending", "doing"),
    ("actions", AccountActionTask, "pending", "doing"),
    ("collections", KeywordCollectionJob, "pending", "running"),
)


def _database_ok() -> tuple[bool, str]:
    try:
        with get_session() as session:
            session.exec(select(PublishTask.id).limit(1)).first()
        return True, ""
    except Exception as exc:
        return False, repr(exc)[:500]


def _queue_metrics(*, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.utcnow()
    queues: dict[str, Any] = {}
    total_pending = 0
    total_running = 0
    oldest_pending_age = 0.0
    with get_session() as session:
        for name, model, pending_status, running_status in _QUEUE_SPECS:
            pending_rows = session.exec(
                select(model).where(model.status == pending_status)
            ).all()
            running_rows = session.exec(
                select(model).where(model.status == running_status)
            ).all()
            oldest = 0.0
            for row in pending_rows:
                created = getattr(row, "created_at", None)
                if created:
                    oldest = max(oldest, max(0.0, (current - created).total_seconds()))
            queues[name] = {
                "pending": len(pending_rows),
                "running": len(running_rows),
                "oldest_pending_age_seconds": oldest,
            }
            total_pending += len(pending_rows)
            total_running += len(running_rows)
            oldest_pending_age = max(oldest_pending_age, oldest)
    return {
        "total_pending": total_pending,
        "total_running": total_running,
        "oldest_pending_age_seconds": oldest_pending_age,
        "queues": queues,
    }


def _heartbeat_stale_after_seconds(engine: Any) -> int:
    cfg = getattr(engine, "cfg", None)
    ecfg = getattr(cfg, "engine", None)
    scan = int(getattr(ecfg, "scan_interval_seconds", 300) or 300)
    download = int(getattr(ecfg, "download_timeout_seconds", 120) or 120)
    captcha = int(getattr(ecfg, "douyin_captcha_wait_seconds", 300) or 300)
    # Some browser stages legitimately wait for uploads/verification.  Readiness
    # should catch a dead scheduler, not flap during one expected long stage.
    return max(600, scan * 2, download + 60, captcha + 60)


def build_runtime_readiness(*, engine: Any, browser: Any,
                            executor_lock: Any,
                            now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.utcnow()
    db_ok, db_error = _database_ok()
    engine_status = (
        engine.runtime_status(now=current)
        if engine is not None and callable(getattr(engine, "runtime_status", None))
        else {}
    )
    stale_after = _heartbeat_stale_after_seconds(engine) if engine is not None else 600
    heartbeat_age = engine_status.get("scheduler_heartbeat_age_seconds")
    scheduler_groups = engine_status.get("scheduler_groups") or {}
    if scheduler_groups:
        groups_alive = all(bool(group.get("alive")) for group in scheduler_groups.values())
        groups_fresh = all(
            group.get("heartbeat_age_seconds") is not None
            and float(group.get("heartbeat_age_seconds")) <= stale_after
            for group in scheduler_groups.values()
        )
        heartbeat_fresh = groups_alive and groups_fresh
    else:
        groups_alive = True
        groups_fresh = True
        heartbeat_fresh = (
            heartbeat_age is not None and float(heartbeat_age) <= stale_after
        )
    checks = {
        "database": db_ok,
        "browser": browser is not None,
        "executor_lock": bool(executor_lock is not None and getattr(executor_lock, "acquired", False)),
        "engine_running": bool(engine_status.get("running")),
        "engine_task_alive": bool(engine_status.get("task_alive")),
        "scheduler_groups_alive": groups_alive,
        "scheduler_heartbeat_fresh": heartbeat_fresh,
    }
    ready = all(checks.values())
    try:
        queue = _queue_metrics(now=current) if db_ok else {}
    except Exception as exc:
        queue = {"error": repr(exc)[:500]}
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": checks,
        "database_error": db_error,
        "heartbeat_stale_after_seconds": stale_after,
        "engine": engine_status,
        "queue": queue,
    }
