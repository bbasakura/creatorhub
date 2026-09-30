import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.api.x as x_api
import app.db as db
from app.models import (
    DouyinAccount, XIntelAlert, XIntelBenchmark, XIntelDailyBrief,
    XIntelPostSnapshot, XIntelScan,
)
from app.platforms.x.agent_reach import AgentReachReadAdapter
from app.platforms.x.intel_analysis import (
    black_horse_candidates, explosion_candidates, fallback_digest, trend_windows,
)
from app.services.x_intel_automation import (
    create_daily_brief, daily_brief_due, persist_explosion_alerts,
    scan_schedule,
)
from sqlmodel import select


class _Risk:
    def __init__(self):
        self.success = []
        self.failures = []

    def preflight(self, account_id, kind):
        return SimpleNamespace(allowed=True, reason="", signal="")

    def record_success(self, account_id, kind):
        self.success.append((account_id, kind))

    def record_failure(self, account_id, kind, exc):
        self.failures.append((account_id, kind, exc))


class _Engine:
    def __init__(self):
        self.risk = _Risk()

    @asynccontextmanager
    async def operation_guard(self, *_args, **_kwargs):
        yield


def test_agent_reach_user_profile_normalizes_public_account():
    adapter = AgentReachReadAdapter("sakurakk730", command="twitter")
    payload = {
        "data": {
            "id": "99",
            "name": "Forward",
            "screenName": "Forward_TD",
            "followers": 12345,
            "following": 321,
            "tweets": 456,
            "likes": 789,
            "verified": True,
            "profileImageUrl": "avatar",
        }
    }
    with patch.object(adapter, "_assert_account", AsyncMock(return_value={})), \
         patch.object(adapter, "_run_json", AsyncMock(return_value=payload)) as run:
        profile = asyncio.run(adapter.user_profile("@Forward_TD"))
    assert profile["handle"] == "Forward_TD"
    assert profile["followers"] == 12345
    assert profile["verified"] is True
    run.assert_awaited_once_with(["user", "Forward_TD", "--json"])


def test_create_intel_benchmark_unpacks_normalized_handle_tuple():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-intel-create.db"))
        try:
            with db.get_session() as session:
                account = DouyinAccount(
                    platform="x",
                    nickname="@sakurakk730",
                    sec_uid="sakurakk730",
                    storage_state="{}",
                    status="active",
                )
                session.add(account)
                session.commit()
                session.refresh(account)
                account_id = account.id

            class FakeAdapter:
                async def user_profile(self, handle):
                    assert isinstance(handle, str)
                    assert handle == "sh11668"
                    return {
                        "handle": handle,
                        "nickname": "SH",
                        "avatar": "",
                        "followers": 123,
                        "following": 45,
                        "tweets": 67,
                        "verified": False,
                    }

            engine = _Engine()
            body = x_api.XIntelBenchmarkIn(
                account_id=account_id,
                handle="https://x.com/sh11668",
                note="test",
            )
            with patch.object(x_api, "_runtime", return_value=(object(), engine)), \
                 patch.object(x_api, "_agent_reach_adapter", return_value=FakeAdapter()):
                result = asyncio.run(x_api.create_intel_benchmark(body))

            assert result["ok"] is True
            assert result["benchmark"]["handle"] == "sh11668"
            assert result["benchmark"]["nickname"] == "SH"
            with db.get_session() as session:
                rows = session.exec(select(XIntelBenchmark)).all()
                assert len(rows) == 1
                assert rows[0].handle == "sh11668"
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_trend_windows_uses_real_nearby_snapshots_and_rejects_far_samples():
    latest_at = datetime(2026, 9, 30, 12, 0, 0)
    latest = SimpleNamespace(
        fetched_at=latest_at, view_count=5000, like_count=500,
        reply_count=80, retweet_count=120)
    near_3h = SimpleNamespace(
        fetched_at=latest_at - timedelta(hours=3, minutes=10),
        view_count=3200, like_count=320, reply_count=50, retweet_count=70)
    far_20h = SimpleNamespace(
        fetched_at=latest_at - timedelta(hours=20),
        view_count=1000, like_count=100, reply_count=10, retweet_count=20)

    trends = trend_windows(latest, [near_3h, far_20h])
    assert trends["3"]["available"] is True
    assert trends["3"]["view_delta"] == 1800
    assert trends["3"]["elapsed_hours"] == 3.17
    assert trends["6"]["available"] is False
    assert trends["24"]["available"] is True
    assert trends["24"]["view_delta"] == 4000


def test_black_horse_candidates_respects_follower_cap_and_efficiency():
    items = [
        {
            "author_handle": "small_hot", "author_name": "Small Hot",
            "author_verified": True, "author_followers": 2000,
            "view_count": 40000, "exposure_efficiency": 20.0,
            "engagement_rate": 0.08,
            "trends": {"3": {"available": True, "views_per_hour": 3000, "view_delta": 9000}},
        },
        {
            "author_handle": "big_account", "author_name": "Big",
            "author_verified": True, "author_followers": 500000,
            "view_count": 300000, "exposure_efficiency": 0.6,
            "engagement_rate": 0.02, "trends": {},
        },
        {
            "author_handle": "small_ok", "author_name": "Small OK",
            "author_verified": False, "author_followers": 8000,
            "view_count": 16000, "exposure_efficiency": 2.0,
            "engagement_rate": 0.03, "trends": {},
        },
    ]
    rows = black_horse_candidates(items, max_followers=50000, limit=20)
    assert [row["handle"] for row in rows] == ["small_hot", "small_ok"]
    assert rows[0]["black_horse_score"] > rows[1]["black_horse_score"]
    assert rows[0]["best_growth"]["window_hours"] == 3


def test_explosion_candidates_require_real_history_and_thresholds():
    no_history = [{
        "tweet_id": "quiet", "author_handle": "quiet",
        "view_count": 100000, "exposure_efficiency": 20.0,
        "engagement_rate": 0.10,
        "trends": {
            "3": {"available": False},
            "6": {"available": False},
            "24": {"available": False},
        },
    }]
    assert explosion_candidates(no_history) == []

    rows = explosion_candidates([{
        "tweet_id": "boom", "tweet_url": "https://x.com/a/status/boom",
        "author_handle": "a", "author_name": "A",
        "view_count": 12000, "exposure_efficiency": 3.0,
        "engagement_rate": 0.04,
        "trends": {
            "3": {
                "available": True, "view_delta": 3600,
                "views_per_hour": 1200, "view_growth_pct": 42.0,
            },
            "6": {"available": False},
            "24": {"available": False},
        },
    }])
    assert len(rows) == 1
    assert rows[0]["tweet_id"] == "boom"
    assert rows[0]["window_hours"] == 3
    assert rows[0]["level"] == "hot"


def test_intel_automation_schedule_does_not_repeat_before_interval():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-intel-schedule.db"))
        try:
            now = datetime(2026, 9, 30, 6, 0, 0)
            with db.get_session() as session:
                account = DouyinAccount(
                    platform="x", nickname="@a", sec_uid="a",
                    storage_state="{}", status="active")
                session.add(account)
                session.commit()
                session.refresh(account)
                scan = XIntelScan(
                    account_id=account.id, status="done",
                    requested_accounts=1, successful_accounts=1,
                    post_count=1, posts_per_account=5,
                    started_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=2))
                session.add(scan)
                session.commit()
                account_id = account.id

            cfg = {"enabled": True, "interval_hours": 3}
            early = scan_schedule(account_id, cfg, now=now)
            assert early["due"] is False
            assert early["next_scan_at"].startswith("2026-09-30T08:58:00")

            due = scan_schedule(
                account_id, cfg, now=now + timedelta(hours=3, minutes=1))
            assert due["due"] is True

            with db.get_session() as session:
                session.add(XIntelScan(
                    account_id=account_id, status="running",
                    requested_accounts=1, posts_per_account=5,
                    started_at=now + timedelta(hours=4)))
                session.commit()
            blocked = scan_schedule(
                account_id, cfg, now=now + timedelta(hours=8))
            assert blocked["running"] is True
            assert blocked["due"] is False
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_explosion_alert_and_daily_brief_are_idempotent():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-intel-auto-state.db"))
        try:
            with db.get_session() as session:
                account = DouyinAccount(
                    platform="x", nickname="@a", sec_uid="a",
                    storage_state="{}", status="active",
                    timezone_id="Asia/Shanghai")
                session.add(account)
                session.commit()
                session.refresh(account)
                scan = XIntelScan(
                    account_id=account.id, status="done",
                    requested_accounts=1, successful_accounts=1,
                    post_count=1, posts_per_account=5,
                    finished_at=datetime(2026, 9, 30, 11, 0, 0))
                session.add(scan)
                session.commit()
                session.refresh(scan)
                account_id, scan_id = account.id, scan.id
                session.expunge(account)

            candidate = {
                "tweet_id": "boom-1",
                "tweet_url": "https://x.com/a/status/boom-1",
                "author_handle": "a", "author_name": "A",
                "level": "exploding", "window_hours": 3,
                "view_count": 9000, "view_delta": 3000,
                "views_per_hour": 1000, "exposure_efficiency": 2.0,
                "engagement_rate": 0.04, "signal_score": 123.4,
                "reason": "3h +3000曝光",
            }
            first = persist_explosion_alerts(account_id, scan_id, [candidate])
            second = persist_explosion_alerts(account_id, scan_id, [candidate])
            assert len(first) == 1
            assert second == []
            with db.get_session() as session:
                assert len(session.exec(select(XIntelAlert)).all()) == 1

            cfg = {
                "enabled": True,
                "daily_brief_enabled": True,
                "daily_brief_hour": 20,
            }
            before = daily_brief_due(
                account, cfg,
                now_utc=datetime(2026, 9, 30, 11, 30, tzinfo=timezone.utc))
            assert before["local_date"] == "2026-09-30"
            assert before["due"] is False

            after = daily_brief_due(
                account, cfg,
                now_utc=datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc))
            assert after["due"] is True

            summary = {"headline": "日报", "overview": "测试"}
            brief1 = create_daily_brief(
                account_id, after["local_date"], scan_id,
                summary, "model", 1)
            brief2 = create_daily_brief(
                account_id, after["local_date"], scan_id,
                {"headline": "不应覆盖"}, "rules", 99)
            assert brief1.id == brief2.id
            assert brief2.summary_source == "model"
            with db.get_session() as session:
                assert len(session.exec(select(XIntelDailyBrief)).all()) == 1

            done = daily_brief_due(
                account, cfg,
                now_utc=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc))
            assert done["due"] is False
            assert done["existing_brief_id"] == brief1.id
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_fallback_digest_is_grounded_in_current_items():
    items = [{
        "tweet_id": "100", "author_handle": "alice",
        "text": "今天测试了新的 AI 工具，速度快很多",
        "view_count": 12000, "exposure_efficiency": 12.0,
        "radar_score": 150,
    }]
    digest = fallback_digest(items, [{
        "handle": "alice", "reason": "1000粉 · 帖均曝光12000 · 平均效率12.0x"
    }])
    assert digest["topics"][0]["evidence_tweet_ids"] == ["100"]
    assert "alice" in digest["topics"][0]["why"]
    assert digest["watchlist"][0]["handle"] == "alice"


def test_intel_metrics_rewards_reach_efficiency_and_engagement():
    post = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {"view": 10000, "like": 500, "reply": 50, "retweet": 100},
    }
    metrics = x_api._intel_metrics(post, followers=1000)
    assert metrics["views"] == 10000
    assert metrics["efficiency"] == 10.0
    assert metrics["engagement_rate"] == 0.08
    assert metrics["score"] > 0


def test_intel_scan_persists_snapshots_and_coverage_without_writing_x():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-intel.db"))
        try:
            with db.get_session() as session:
                account = DouyinAccount(
                    platform="x",
                    nickname="@sakurakk730",
                    sec_uid="sakurakk730",
                    storage_state="{}",
                    status="active",
                )
                session.add(account)
                session.commit()
                session.refresh(account)
                benchmark = XIntelBenchmark(
                    account_id=account.id,
                    handle="Forward_TD",
                    nickname="Forward",
                    follower_count=1000,
                    verified=True,
                    enabled=True,
                    last_synced_at=datetime.utcnow(),
                )
                session.add(benchmark)
                session.commit()
                session.refresh(benchmark)
                account_id = account.id

            class FakeAdapter:
                async def user_posts(self, handle, count=5):
                    assert handle == "Forward_TD"
                    assert count == 3
                    return [
                        {
                            "id": "2106000000000000001",
                            "url": "https://x.com/Forward_TD/status/2106000000000000001",
                            "text": "第一条高曝光帖子",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "author": {
                                "handle": "Forward_TD",
                                "name": "Forward",
                                "verified": True,
                            },
                            "metrics": {
                                "view": 12000, "like": 600,
                                "reply": 80, "retweet": 120,
                            },
                        },
                        {
                            "id": "2106000000000000002",
                            "url": "https://x.com/Forward_TD/status/2106000000000000002",
                            "text": "第二条帖子",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "author": {
                                "handle": "Forward_TD",
                                "name": "Forward",
                                "verified": True,
                            },
                            "metrics": {
                                "view": 2000, "like": 50,
                                "reply": 5, "retweet": 10,
                            },
                        },
                    ]

            engine = _Engine()
            body = x_api.XIntelScanIn(
                account_id=account_id,
                posts_per_account=3,
                max_accounts=30,
            )
            with patch.object(x_api, "_runtime", return_value=(object(), engine)), \
                 patch.object(x_api, "_agent_reach_adapter", return_value=FakeAdapter()):
                result = asyncio.run(x_api.scan_x_intel(body))

            assert result["ok"] is True
            assert result["scan"]["status"] == "done"
            assert result["scan"]["coverage"] == 100.0
            assert result["scan"]["requested_accounts"] == 1
            assert result["scan"]["successful_accounts"] == 1
            assert result["scan"]["post_count"] == 2
            assert len(result["items"]) == 2
            assert result["items"][0]["tweet_id"] == "2106000000000000001"
            assert result["items"][0]["author_verified"] is True
            assert result["items"][0]["exposure_efficiency"] == 12.0
            assert result["items"][0]["radar_score"] > result["items"][1]["radar_score"]
            assert result["signals"] == []
            assert result["new_alerts"] == []

            with db.get_session() as session:
                scans = session.exec(select(XIntelScan)).all()
                snapshots = session.exec(select(XIntelPostSnapshot)).all()
                assert len(scans) == 1
                assert len(snapshots) == 2
                assert scans[0].status == "done"
                assert scans[0].successful_accounts == 1
                assert scans[0].failed_accounts == 0

            assert engine.risk.failures == []
            assert len(engine.risk.success) == 1
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_intel_digest_persists_summary_and_reuses_cache():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-intel-digest.db"))
        try:
            with db.get_session() as session:
                account = DouyinAccount(
                    platform="x", nickname="@sakurakk730", sec_uid="sakurakk730",
                    storage_state="{}", status="active")
                session.add(account)
                session.commit()
                session.refresh(account)
                scan = XIntelScan(
                    account_id=account.id, status="done",
                    requested_accounts=1, successful_accounts=1,
                    post_count=1, posts_per_account=5,
                    finished_at=datetime.utcnow())
                session.add(scan)
                session.commit()
                session.refresh(scan)
                snapshot = XIntelPostSnapshot(
                    scan_id=scan.id, account_id=account.id,
                    tweet_id="2107000000000000001",
                    tweet_url="https://x.com/alice/status/2107000000000000001",
                    author_handle="alice", author_name="Alice",
                    author_followers=1000, text="一条用于情报总结的帖子",
                    view_count=12000, like_count=500, reply_count=30,
                    retweet_count=50, exposure_efficiency=12.0,
                    engagement_rate=0.0525, radar_score=140,
                    fetched_at=datetime.utcnow())
                session.add(snapshot)
                session.commit()
                account_id, scan_id = account.id, scan.id

            digest = {
                "headline": "测试总结",
                "overview": "只基于当前扫描。",
                "topics": [], "opportunities": [],
                "watchlist": [], "watchouts": ["样本有限"],
            }
            with patch.object(
                    x_api, "generate_digest",
                    AsyncMock(return_value=(digest, "model"))) as generate:
                result = asyncio.run(x_api.generate_intel_digest(
                    x_api.XIntelDigestIn(
                        account_id=account_id, scan_id=scan_id, force=False)))
                assert result["scan"]["digest"]["headline"] == "测试总结"
                assert result["scan"]["summary_source"] == "model"
                assert result["cached"] is False

                cached = asyncio.run(x_api.generate_intel_digest(
                    x_api.XIntelDigestIn(
                        account_id=account_id, scan_id=scan_id, force=False)))
                assert cached["cached"] is True
                assert generate.await_count == 1

            with db.get_session() as session:
                saved = session.get(XIntelScan, scan_id)
                assert json.loads(saved.summary_json)["headline"] == "测试总结"
                assert saved.summary_source == "model"
                assert saved.summary_generated_at is not None
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_intel_scan_source_is_read_only_and_ui_actions_are_draft_only():
    source = Path("app/api/x.py").read_text(encoding="utf-8")
    block = source[source.index('@router.post("/intel/scan")'):]
    block = block[:block.index("class XRelationshipIn")]
    assert "user_posts(" in block
    assert "reply_x(" not in block
    assert "create_x_reply_draft(" not in block
    assert "perform_queue_action(" not in block

    index = Path("app/web/index.html").read_text(encoding="utf-8")
    js = Path("app/web/x_intel.js").read_text(encoding="utf-8")
    app_js = Path("app/web/app.js").read_text(encoding="utf-8")
    assert 'data-tab="x-intel"' in index
    assert 'data-panel="x-intel"' in index
    assert "/api/x/intel/scan" in js
    assert "/api/x/intel/benchmarks" in js
    assert "/api/x/intel/black-horses" in js
    assert "/api/x/intel/digest" in js
    assert "/api/x/intel/automation" in js
    assert "/api/x/intel/alerts" in js
    assert "/api/x/intel/daily-briefs" in js
    assert 'id="x-intel-auto-status"' in index
    assert 'id="x-intel-alert-table"' in index
    assert 'id="x-intel-daily-brief-list"' in index
    assert 'id="x-intel-blackhorse-table"' in index
    assert 'id="x-intel-digest"' in index
    assert "3h / 6h / 24h 增速" in index
    assert "/api/x/reply/preview" in js
    assert "/api/x/reply/draft" in js
    assert 'api("/api/x/reply", ' not in js
    assert '"x-intel"' in app_js

    monitor = Path("app/engine/monitor.py").read_text(encoding="utf-8")
    assert 'SchedulerGroup("intel", 60.0' in monitor
    assert "_process_x_intel_automation" in monitor
    assert "scan_x_intel(XIntelScanIn(" in monitor
