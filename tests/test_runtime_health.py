from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.runtime_health import build_runtime_readiness


class FakeEngine:
    def __init__(self, age=3.0, *, running=True, task_alive=True):
        self.age = age
        self.running = running
        self.task_alive = task_alive
        self.cfg = SimpleNamespace(engine=SimpleNamespace(
            scan_interval_seconds=300,
            download_timeout_seconds=120,
            douyin_captcha_wait_seconds=300,
        ))

    def runtime_status(self, *, now=None):
        return {
            "running": self.running,
            "task_alive": self.task_alive,
            "scheduler_heartbeat_age_seconds": self.age,
            "scheduler_stage": "publish_queue",
            "scheduler_groups": {},
        }


class FakeLock:
    acquired = True


def test_readiness_requires_live_fresh_single_executor():
    with patch("app.services.runtime_health._database_ok", return_value=(True, "")), \
         patch("app.services.runtime_health._queue_metrics", return_value={"total_pending": 0}):
        payload = build_runtime_readiness(
            engine=FakeEngine(), browser=object(), executor_lock=FakeLock(),
            now=datetime(2026, 9, 29, 4, 0, 0))
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["checks"]["scheduler_heartbeat_fresh"] is True


def test_readiness_rejects_stale_scheduler_heartbeat():
    with patch("app.services.runtime_health._database_ok", return_value=(True, "")), \
         patch("app.services.runtime_health._queue_metrics", return_value={}):
        payload = build_runtime_readiness(
            engine=FakeEngine(age=601), browser=object(), executor_lock=FakeLock())
    assert payload["ready"] is False
    assert payload["checks"]["scheduler_heartbeat_fresh"] is False


def test_readiness_checks_each_scheduler_group_when_present():
    engine = FakeEngine(age=9999)
    def status(*, now=None):
        return {
            "running": True,
            "task_alive": True,
            "scheduler_heartbeat_age_seconds": 9999,
            "scheduler_groups": {
                "scan": {"alive": True, "heartbeat_age_seconds": 2},
                "writes": {"alive": True, "heartbeat_age_seconds": 3},
                "maintenance": {"alive": True, "heartbeat_age_seconds": 4},
            },
        }
    engine.runtime_status = status
    with patch("app.services.runtime_health._database_ok", return_value=(True, "")), \
         patch("app.services.runtime_health._queue_metrics", return_value={}):
        payload = build_runtime_readiness(
            engine=engine, browser=object(), executor_lock=FakeLock())
    assert payload["ready"] is True
    assert payload["checks"]["scheduler_groups_alive"] is True


def test_readiness_rejects_dead_scheduler_group():
    engine = FakeEngine()
    def status(*, now=None):
        return {
            "running": True,
            "task_alive": True,
            "scheduler_heartbeat_age_seconds": 1,
            "scheduler_groups": {
                "scan": {"alive": False, "heartbeat_age_seconds": 2},
                "writes": {"alive": True, "heartbeat_age_seconds": 3},
            },
        }
    engine.runtime_status = status
    with patch("app.services.runtime_health._database_ok", return_value=(True, "")), \
         patch("app.services.runtime_health._queue_metrics", return_value={}):
        payload = build_runtime_readiness(
            engine=engine, browser=object(), executor_lock=FakeLock())
    assert payload["ready"] is False
    assert payload["checks"]["scheduler_groups_alive"] is False


def test_readiness_rejects_missing_executor_lock():
    with patch("app.services.runtime_health._database_ok", return_value=(True, "")), \
         patch("app.services.runtime_health._queue_metrics", return_value={}):
        payload = build_runtime_readiness(
            engine=FakeEngine(), browser=object(), executor_lock=None)
    assert payload["ready"] is False
    assert payload["checks"]["executor_lock"] is False
