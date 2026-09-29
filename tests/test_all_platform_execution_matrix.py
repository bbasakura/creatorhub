import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import app.db as db
from app.config import Config, EngineConfig
from app.engine.monitor import MonitorEngine
from app.models import DouyinAccount, PublishTask
from app.services.publish_idempotency import persist_direct_publish


PLATFORMS = (
    "x", "wechat_mp", "shipinhao", "douyin",
    "kuaishou", "xhs", "youtube",
)
BROWSER_PLATFORMS = ("x", "shipinhao", "douyin", "kuaishou", "xhs")
ALWAYS_UNCERTAIN_ON_INTERRUPTED_PUBLISH = ("wechat_mp", "youtube")


class _BrowserStub:
    pass


@pytest.fixture()
def isolated_db():
    previous = db._engine
    tmp = tempfile.TemporaryDirectory()
    db.init_db(str(Path(tmp.name) / "all-platform-matrix.db"))
    try:
        yield tmp
    finally:
        if db._engine is not None:
            db._engine.dispose()
        db._engine = previous
        tmp.cleanup()


def _engine(tmp) -> MonitorEngine:
    cfg = Config(engine=EngineConfig(
        media_dir=str(Path(tmp.name) / "media"),
        profiles_dir=str(Path(tmp.name) / "profiles"),
        quiet_hours_enabled=False,
    ))
    cfg.risk_control.enabled = False
    return MonitorEngine(cfg, _BrowserStub())


def _account(platform: str) -> int:
    with db.get_session() as session:
        row = DouyinAccount(
            platform=platform, nickname=f"fixture-{platform}", status="active",
            storage_state='{"cookies": []}', creator_storage_state='{"cookies": []}',
        )
        session.add(row); session.commit(); session.refresh(row)
        return row.id


def _task(platform: str, account_id: int, *, status: str = "publishing",
          error: str = "") -> int:
    with db.get_session() as session:
        row = PublishTask(
            platform=platform, account_id=account_id, media_type="video",
            media_json="[]", status=status, error=error,
        )
        session.add(row); session.commit(); session.refresh(row)
        return row.id


@pytest.mark.parametrize("platform", PLATFORMS)
def test_all_platforms_explicit_intent_replay_is_idempotent(isolated_db, platform):
    account_id = _account(platform)
    key = f"publish:{account_id}:client:matrix-{platform}"
    with db.get_session() as session:
        first, replay = persist_direct_publish(session, PublishTask(
            platform=platform, account_id=account_id,
            content_fingerprint="fixture-fp", source_intent_key=key,
        ), explicit_intent=True)
        assert replay is False
        second, replay = persist_direct_publish(session, PublishTask(
            platform=platform, account_id=account_id,
            content_fingerprint="fixture-fp", source_intent_key=key,
        ), explicit_intent=True)
        assert replay is True
        assert second.id == first.id


@pytest.mark.parametrize("platform", PLATFORMS)
def test_all_platforms_pre_submit_failure_never_becomes_done(isolated_db, platform):
    account_id = _account(platform)
    task_id = _task(platform, account_id)
    engine = _engine(isolated_db)
    result = asyncio.run(engine._finish_publish(
        task_id, False, "", "adapter_failed:fixture", platform=platform))
    assert result["ok"] is False
    with db.get_session() as session:
        row = session.get(PublishTask, task_id)
        assert row.status == "failed"
        assert row.done_at is None


@pytest.mark.parametrize("platform", PLATFORMS)
def test_all_platforms_post_submit_unknown_is_uncertain_and_not_scheduled(isolated_db, platform):
    account_id = _account(platform)
    task_id = _task(platform, account_id, error="write_submitted:browser")
    engine = _engine(isolated_db)
    result = asyncio.run(engine._finish_publish(
        task_id, False, "", "write_uncertain:fixture", platform=platform))
    assert result["ok"] is False
    with db.get_session() as session:
        row = session.get(PublishTask, task_id)
        assert row.status == "uncertain"
        assert row.scheduled_at is None
        assert row.done_at is None


@pytest.mark.parametrize("platform", PLATFORMS)
def test_all_platforms_positive_success_receipt_marks_done(isolated_db, platform):
    account_id = _account(platform)
    task_id = _task(platform, account_id)
    url = (
        "https://mp.weixin.qq.com/#draft=draft-fixture" if platform == "wechat_mp"
        else "https://www.youtube.com/watch?v=video-fixture" if platform == "youtube"
        else f"https://example.invalid/{platform}/success"
    )
    engine = _engine(isolated_db)
    result = asyncio.run(engine._finish_publish(
        task_id, True, url, "", platform=platform))
    assert result["ok"] is True
    with db.get_session() as session:
        row = session.get(PublishTask, task_id)
        assert row.status == "done"
        assert row.done_at is not None
        assert row.result_url == url
        if platform == "wechat_mp":
            assert row.platform_result_id == "draft-fixture"
        if platform == "youtube":
            assert row.platform_result_id == "video-fixture"


@pytest.mark.parametrize("platform", BROWSER_PLATFORMS)
def test_browser_platform_interrupted_before_submit_recovers_pending(isolated_db, platform):
    account_id = _account(platform)
    task_id = _task(platform, account_id)
    now = datetime(2026, 9, 29, 12, 0, 0)
    engine = _engine(isolated_db)
    assert engine.recover_interrupted_tasks(now=now) == 1
    with db.get_session() as session:
        row = session.get(PublishTask, task_id)
        assert row.status == "pending"
        assert row.scheduled_at == now + timedelta(minutes=5)


@pytest.mark.parametrize("platform", BROWSER_PLATFORMS)
def test_browser_platform_interrupted_after_submit_recovers_uncertain(isolated_db, platform):
    account_id = _account(platform)
    task_id = _task(platform, account_id, error="write_submitted:browser")
    engine = _engine(isolated_db)
    assert engine.recover_interrupted_tasks(now=datetime(2026, 9, 29, 12, 0, 0)) == 1
    with db.get_session() as session:
        row = session.get(PublishTask, task_id)
        assert row.status == "uncertain"
        assert row.scheduled_at is None


@pytest.mark.parametrize("platform", ALWAYS_UNCERTAIN_ON_INTERRUPTED_PUBLISH)
def test_non_browser_resumable_or_draft_writer_interruption_is_uncertain(isolated_db, platform):
    account_id = _account(platform)
    task_id = _task(platform, account_id)
    engine = _engine(isolated_db)
    assert engine.recover_interrupted_tasks(now=datetime(2026, 9, 29, 12, 0, 0)) == 1
    with db.get_session() as session:
        row = session.get(PublishTask, task_id)
        assert row.status == "uncertain"
        assert row.scheduled_at is None
