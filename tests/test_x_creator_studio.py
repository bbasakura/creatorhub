import tempfile
from pathlib import Path

import app.db as db
from app.models import DouyinAccount, XCreatorStudioSnapshot, XRevenueProfile
from app.platforms.x.creator_studio import _analytics_payload, _parse_rewards_progress
from app.services.x_growth_dashboard import (
    build_growth_dashboard,
    persist_creator_studio_official,
)
from sqlmodel import select


def _init_tmp():
    previous = db._engine
    tmp = tempfile.TemporaryDirectory()
    db.init_db(str(Path(tmp.name) / "creator-studio.db"))
    return previous, tmp


def _restore(previous, tmp):
    if db._engine is not None:
        db._engine.dispose()
    db._engine = previous
    tmp.cleanup()


def test_rewards_progress_parses_current_value_not_threshold():
    text = """
稍后再查看
再完成几个步骤，你就能加入原创内容奖励计划，并通过发布原创内容赚取收益。
至少有 500 名已验证粉丝
过去 90 天内，累积至少 50 万次已验证首页时间线曝光

660

回复不计入曝光
"""
    result = _parse_rewards_progress(text)
    assert result["rewards_ok"] is True
    assert result["qualified_impressions_90d"] == 660
    assert result["not_eligible"] is True


def test_analytics_payload_normalizes_official_metrics_and_daily_series():
    payload = {
        "data": {
            "viewer_v2": {
                "user_results": {
                    "result": {
                        "verified_follower_count": "550",
                        "relationship_counts": {"followers": 590},
                        "current_time_series": [
                            {
                                "count": 1000,
                                "engagement_type": "Displayed",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 200,
                                "engagement_type": "Displayed",
                                "is_engaging_user_verified": "false",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 60,
                                "engagement_type": "ProfilePic",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 45,
                                "engagement_type": "Reply",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 85,
                                "engagement_type": "Fav",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 1,
                                "engagement_type": "Bookmark",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 2,
                                "engagement_type": "QuoteCreate",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 12,
                                "engagement_type": "TweetCreate",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                            {
                                "count": 20,
                                "engagement_type": "ReplyCreate",
                                "is_engaging_user_verified": "true",
                                "timestamp": 1790208000000,
                            },
                        ],
                        "legacy_current_follow_metrics": [
                            {
                                "metric_values": [
                                    {"metric_type": "Follows", "metric_value": 13},
                                    {"metric_type": "Unfollows", "metric_value": 2},
                                ],
                                "timestamp": {"iso8601_time": "2026-09-24T00:00:00Z"},
                            }
                        ],
                    }
                }
            }
        }
    }
    result = _analytics_payload(payload)
    assert result["analytics_ok"] is True
    assert result["verified_followers"] == 550
    assert result["follower_count"] == 590
    assert result["impressions"] == 1200
    assert result["verified_impressions"] == 1000
    assert result["unverified_impressions"] == 200
    assert result["profile_visits"] == 60
    assert result["replies"] == 45
    assert result["likes"] == 85
    assert result["bookmarks"] == 1
    assert result["engagements"] == 193
    assert result["engagement_rate"] == round(193 / 1200, 6)
    assert result["follows"] == 13
    assert result["unfollows"] == 2
    assert result["posts"] == 12
    assert result["reply_posts"] == 20
    assert result["daily"][0]["verified_impressions"] == 1000


def test_official_snapshot_overrides_manual_fallback_in_dashboard():
    previous, tmp = _init_tmp()
    try:
        with db.get_session() as session:
            account = DouyinAccount(
                platform="x",
                nickname="Sakura",
                sec_uid="sakurakk730",
                follower_count=10,
                storage_state="{}",
                status="active",
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = int(account.id)
            session.add(XRevenueProfile(
                account_id=account_id,
                official_verified_followers=0,
                official_qualified_impressions_90d=0,
            ))
            session.commit()

        snapshot = persist_creator_studio_official(account_id, {
            "analytics_ok": True,
            "rewards_ok": True,
            "verified_followers": 550,
            "follower_count": 590,
            "impressions": 2920,
            "verified_impressions": 2523,
            "unverified_impressions": 397,
            "engagements": 195,
            "engagement_rate": 0.064,
            "profile_visits": 60,
            "replies": 46,
            "likes": 88,
            "reposts": 0,
            "bookmarks": 1,
            "shares": 0,
            "follows": 583,
            "unfollows": 12,
            "posts": 288,
            "reply_posts": 567,
            "qualified_impressions_90d": 660,
            "daily": [{"date": "2026-09-30", "impressions": 199}],
            "analytics_url": "https://x.com/i/account_analytics",
            "rewards_url": "https://x.com/i/jf/creators/original_content_rewards",
            "not_eligible": True,
        })
        assert snapshot["verified_followers"] == 550
        assert snapshot["qualified_impressions_90d"] == 660

        payload = build_growth_dashboard(account_id)
        assert payload["account"]["followers"] == 590
        assert payload["revenue"]["official_source"] == "x_creator_studio"
        assert payload["revenue"]["official_verified_followers"] == 550
        assert payload["revenue"]["official_qualified_impressions_90d"] == 660
        assert payload["creator_studio"]["analytics_ok"] is True
        assert payload["creator_studio"]["rewards_ok"] is True
        assert payload["creator_studio"]["impressions"] == 2920
        assert payload["creator_studio"]["daily"][0]["date"] == "2026-09-30"

        with db.get_session() as session:
            official = session.exec(select(XCreatorStudioSnapshot)).all()
            profile = session.exec(select(XRevenueProfile)).first()
            assert len(official) == 1
            assert official[0].verified_followers == 550
            assert official[0].qualified_impressions_90d == 660
            assert profile.official_verified_followers == 550
            assert profile.official_qualified_impressions_90d == 660
            assert profile.rewards_enrolled is False
    finally:
        _restore(previous, tmp)


def test_creator_studio_ui_and_read_only_route_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/x_intel.js").read_text(encoding="utf-8")
    api_source = (root / "app/api/x.py").read_text(encoding="utf-8")
    reader = (root / "app/platforms/x/creator_studio.py").read_text(encoding="utf-8")

    assert "同步 X 官方数据" in html
    assert 'id="x-official-impressions"' in html
    assert 'id="x-official-engagement-rate"' in html
    assert 'id="x-official-daily-table"' in html
    assert "/api/x/growth-dashboard/official-sync" in js
    assert "syncXCreatorStudioOfficial" in js

    block = api_source[api_source.index('@router.post("/growth-dashboard/official-sync")'):]
    block = block[:block.index('@router.put("/growth-dashboard/settings")')]
    assert "OperationKind.READ_HEAVY" in block
    assert "fetch_creator_studio_official" in block
    assert "publish_x(" not in block
    assert "reply_x(" not in block
    assert "create_x_post_draft(" not in block
    assert "create_x_reply_draft(" not in block

    assert "accountOverviewDailyQuery" in reader
    assert "REWARDS_URL" in reader
    assert "page.locator(\"body\").inner_text" in reader
