import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.db as db
from app.models import (
    AccountWork,
    DouyinAccount,
    FollowEdge,
    XAccountGrowthSnapshot,
    XRevenueProfile,
    XWorkMetricSnapshot,
)
from app.services.x_growth_dashboard import build_growth_dashboard
from sqlmodel import select


def _init_tmp():
    previous = db._engine
    tmp = tempfile.TemporaryDirectory()
    db.init_db(str(Path(tmp.name) / "growth-dashboard.db"))
    return previous, tmp


def _restore(previous, tmp):
    if db._engine is not None:
        db._engine.dispose()
    db._engine = previous
    tmp.cleanup()


def test_growth_dashboard_first_open_creates_default_profile():
    previous, tmp = _init_tmp()
    try:
        with db.get_session() as session:
            account = DouyinAccount(
                platform="x", nickname="First Open", sec_uid="firstopen",
                follower_count=7, storage_state="{}", status="active",
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = int(account.id)

        payload = build_growth_dashboard(account_id)
        assert payload["account"]["followers"] == 7

        with db.get_session() as session:
            row = session.exec(select(XRevenueProfile).where(
                XRevenueProfile.account_id == account_id
            )).first()
            assert row is not None
    finally:
        _restore(previous, tmp)


def test_growth_dashboard_lifecycle_revenue_and_attribution():
    previous, tmp = _init_tmp()
    try:
        now = datetime.utcnow().replace(microsecond=0)
        post_created = now - timedelta(hours=1)
        post_epoch = int(post_created.replace(tzinfo=timezone.utc).timestamp())
        with db.get_session() as session:
            account = DouyinAccount(
                platform="x",
                nickname="Sakura",
                sec_uid="sakurakk730",
                follower_count=120,
                following_count=80,
                aweme_count=2,
                storage_state="{}",
                status="active",
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = int(account.id)

            session.add(XRevenueProfile(
                account_id=account_id,
                premium_active=True,
                official_verified_followers=120,
                official_qualified_impressions_90d=250000,
            ))
            session.add(FollowEdge(
                platform="x", account_id=account_id, direction="fan",
                uid="verified-fan", sec_uid="verifiedfan", nickname="VF",
                raw_json=json.dumps({"verified": True}),
            ))
            work = AccountWork(
                platform="x", account_id=account_id, item_id="tweet-1",
                desc="测试增长帖子", media_type="text",
                create_time=post_epoch,
                play_count=1100, like_count=50, comment_count=10, share_count=5,
            )
            session.add(work)
            session.add(XWorkMetricSnapshot(
                account_id=account_id, item_id="tweet-1",
                create_time=post_epoch,
                play_count=100, like_count=4, comment_count=1, share_count=0,
                captured_at=now - timedelta(minutes=50),
            ))
            session.add(XWorkMetricSnapshot(
                account_id=account_id, item_id="tweet-1",
                create_time=post_epoch,
                play_count=1100, like_count=50, comment_count=10, share_count=5,
                captured_at=now,
            ))
            session.add(XAccountGrowthSnapshot(
                account_id=account_id, follower_count=110,
                following_count=80, post_count=1,
                captured_at=now - timedelta(hours=2),
            ))
            session.add(XAccountGrowthSnapshot(
                account_id=account_id, follower_count=120,
                following_count=80, post_count=2,
                captured_at=now,
            ))
            session.commit()

        payload = build_growth_dashboard(account_id)
        assert payload["revenue"]["synced_verified_followers_lower_bound"] == 1
        assert payload["revenue"]["official_verified_followers"] == 120
        assert payload["revenue"]["official_qualified_impressions_90d"] == 250000
        assert payload["revenue"]["public_impressions_90d_reference"] == 1100

        lifecycle = payload["lifecycle"]["items"][0]
        assert lifecycle["item_id"] == "tweet-1"
        assert lifecycle["windows"]["1"]["available"] is True
        assert lifecycle["windows"]["1"]["views"] == 1100
        assert lifecycle["snapshot_count"] == 2

        attribution = payload["attribution"]["items"]
        assert attribution
        assert attribution[0]["item_id"] == "tweet-1"
        assert attribution[0]["estimated_followers"] == 10.0
    finally:
        _restore(previous, tmp)


def test_growth_dashboard_ui_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/x_intel.js").read_text(encoding="utf-8")
    assert "X 增长与收益驾驶舱" in html
    assert 'id="x-growth-lifecycle-table"' in html
    assert 'id="x-growth-attribution-table"' in html
    assert 'id="x-revenue-safe-mode"' not in html
    assert "收益安全模式" not in html
    assert "/api/x/growth-dashboard" in js
    assert "safe_mode" not in js
