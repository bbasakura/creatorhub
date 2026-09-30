"""RC-1 cadence gates against isolated durable task rows; no X requests."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import select

import app.db as db
from app.config import Config, EngineConfig
from app.engine.monitor import MonitorEngine
from app.models import AccountActionTask, CommentTask, DouyinAccount


@pytest.fixture
def x_engine():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "rc1-cadence.db"))
        cfg = Config(engine=EngineConfig(
            media_dir=str(Path(directory) / "media"),
            profiles_dir=str(Path(directory) / "profiles"),
            quiet_hours_enabled=False,
            action_hourly_cap_per_account=1,
            action_min_gap_seconds=600,
            comment_hourly_cap_per_account=1,
            comment_min_gap_seconds=600,
        ))
        with db.get_session() as session:
            account = DouyinAccount(platform="x", nickname="rc1", status="active")
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = account.id
        try:
            yield MonitorEngine(cfg, object()), account_id
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_x_relationship_worker_gate_uses_task_gap_without_legacy_cap(x_engine):
    engine, account_id = x_engine
    with db.get_session() as session:
        session.add(AccountActionTask(
            platform="x", account_id=account_id, action="follow",
            target_uid="previous", status="done",
            done_at=datetime.utcnow() - timedelta(seconds=60),
        ))
        session.commit()

    assert "随机间隔" in engine._action_gate_error(
        account_id, 75, "follow", x_one_click=True)
    assert engine._action_gate_error(
        account_id, 50, "unfollow", x_one_click=True) == ""
    assert engine._action_gate_error(
        account_id, 50, "unfollow", x_one_click=False) != ""


def test_x_one_click_cadence_keeps_platform_hard_circuit(x_engine):
    engine, account_id = x_engine
    engine.risk.open_platform_circuit(
        "x", reason="RC1 hard circuit verification", actor="test")

    relationship_error = engine._action_gate_error(
        account_id, 50, "follow", x_one_click=True)
    comment_error = engine._x_comment_gate_error(
        account_id, "x_remind:", 50)

    assert "平台硬熔断" in relationship_error
    assert "平台硬熔断" in comment_error


def test_x_comment_worker_gate_uses_remind_and_visit_cadence(x_engine):
    engine, account_id = x_engine
    now = datetime.utcnow()
    with db.get_session() as session:
        reminder_done = CommentTask(
            platform="x", account_id=account_id, aweme_id="old-remind",
            xsec_token="x_remind:old", target_comment_id="old-remind",
            content="old", status="done", done_at=now - timedelta(seconds=30),
        )
        visit_done = CommentTask(
            platform="x", account_id=account_id, aweme_id="old-visit",
            xsec_token="x_visit:old", target_comment_id="old-visit",
            content="old", status="done", done_at=now - timedelta(seconds=200),
        )
        reminder = CommentTask(
            platform="x", account_id=account_id, aweme_id="new-remind",
            xsec_token="x_remind:new", target_comment_id="new-remind",
            content="new", status="pending",
        )
        visit = CommentTask(
            platform="x", account_id=account_id, aweme_id="new-visit",
            xsec_token="x_visit:new", target_comment_id="new-visit",
            content="new", status="pending",
        )
        session.add_all([reminder_done, visit_done, reminder, visit])
        session.commit()
        session.refresh(reminder)
        session.refresh(visit)
        remind_spec = engine._x_comment_gap_spec(reminder)
        visit_spec = engine._x_comment_gap_spec(visit)

    assert remind_spec is not None and 50 <= remind_spec[1] <= 70
    assert visit_spec is not None and 270 <= visit_spec[1] <= 330
    assert "随机间隔" in engine._x_comment_gate_error(account_id, *remind_spec)
    assert "随机间隔" in engine._x_comment_gate_error(account_id, *visit_spec)

    with db.get_session() as session:
        for token, age in (("x_remind:old", 100), ("x_visit:old", 400)):
            row = session.exec(select(CommentTask).where(
                CommentTask.xsec_token == token)).one()
            row.done_at = datetime.utcnow() - timedelta(seconds=age)
            session.add(row)
        session.commit()

    assert engine._x_comment_gate_error(account_id, *remind_spec) == ""
    assert engine._x_comment_gate_error(account_id, *visit_spec) == ""
