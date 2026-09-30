import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path

import app.db as db
from app.api import x as x_api
from app.models import (
    DouyinAccount,
    PublishTask,
    XContentOpportunity,
    XIntelPostSnapshot,
    XIntelScan,
)
from app.services.x_content_strategy import (
    _has_unverified_personal_experience,
    generate_and_persist_opportunities,
)
from app.services.x_intel_automation import normalize_x_intel_automation
from app.services.x_workflow import create_x_post_draft
from sqlmodel import select


def _init_tmp():
    previous = db._engine
    tmp = tempfile.TemporaryDirectory()
    db.init_db(str(Path(tmp.name) / "x-content-opportunity.db"))
    return previous, tmp


def _restore(previous, tmp):
    if db._engine is not None:
        db._engine.dispose()
    db._engine = previous
    tmp.cleanup()


def _items():
    return [
        {
            "tweet_id": "t1",
            "tweet_url": "https://x.com/a/status/t1",
            "author_handle": "a",
            "author_name": "A",
            "text": "某个热门 AI 工具今天突然爆了，所有人都应该立刻照着我的方法做。",
            "view_count": 12000,
            "like_count": 300,
            "reply_count": 60,
            "retweet_count": 80,
            "engagement_rate": 0.04,
            "exposure_efficiency": 12.0,
            "radar_score": 180.0,
            "trends": {"3": {"available": True, "view_delta": 6000, "views_per_hour": 2000}},
        },
        {
            "tweet_id": "t2",
            "tweet_url": "https://x.com/b/status/t2",
            "author_handle": "b",
            "author_name": "B",
            "text": "个人品牌真正重要的是持续输出，而不是追每一个热点。",
            "view_count": 7000,
            "like_count": 200,
            "reply_count": 20,
            "retweet_count": 30,
            "engagement_rate": 0.035,
            "exposure_efficiency": 8.0,
            "radar_score": 150.0,
            "trends": {"3": {"available": True, "view_delta": 2500, "views_per_hour": 833}},
        },
    ]


def _digest():
    return {
        "headline": "AI 工具与个人品牌讨论升温",
        "overview": "本轮只基于对标池样本。",
        "opportunities": [
            {
                "angle": "围绕「AI 工具热度」补充你的实测或观点",
                "why": "t1 本轮增速和曝光效率较高。",
                "evidence_tweet_ids": ["t1"],
            },
            {
                "angle": "围绕「个人品牌持续输出」补充你的实测或观点",
                "why": "t2 的互动和效率稳定。",
                "evidence_tweet_ids": ["t2"],
            },
        ],
    }


def test_rule_opportunities_create_drafts_only_and_dedupe():
    previous, tmp = _init_tmp()
    try:
        with db.get_session() as session:
            account = DouyinAccount(
                platform="x", nickname="@s", sec_uid="s",
                storage_state="{}", status="active")
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = int(account.id)

        first = asyncio.run(generate_and_persist_opportunities(
            account_id, 11, _items(), _digest(), {}, count=2))
        assert len(first) == 2
        assert all(row["status"] == "drafted" for row in first)
        assert all(row["draft_task_id"] for row in first)
        assert all(row["generation_source"] == "rules" for row in first)
        assert all(len(row["draft_text"]) <= 280 for row in first)
        assert first[0]["draft_text"] != _items()[0]["text"]

        with db.get_session() as session:
            tasks = session.exec(select(PublishTask).where(
                PublishTask.account_id == account_id,
                PublishTask.platform == "x",
            )).all()
            opportunities = session.exec(select(XContentOpportunity).where(
                XContentOpportunity.account_id == account_id
            )).all()
            assert len(tasks) == 2
            assert len(opportunities) == 2
            assert all(task.status == "draft" for task in tasks)
            assert not any(task.status == "pending" for task in tasks)

        missing_task_id = int(first[0]["draft_task_id"])
        with db.get_session() as session:
            missing = session.get(PublishTask, missing_task_id)
            session.delete(missing)
            session.commit()

        unrelated = create_x_post_draft(
            account_id, "无关 X 草稿", intent_id="unrelated-id-reuse")
        reused_id = int(unrelated["task_id"])

        second = asyncio.run(generate_and_persist_opportunities(
            account_id, 12, _items(), _digest(), {}, count=2))
        assert [row["id"] for row in second] == [row["id"] for row in first]
        with db.get_session() as session:
            repaired = session.get(PublishTask, int(second[0]["draft_task_id"]))
            assert repaired is not None
            assert repaired.status == "draft"
            assert repaired.source_intent_key == (
                f'x-draft:{account_id}:client:intel-opportunity-'
                f'{first[0]["source_key"][:24]}'
            )
            unrelated_row = session.get(PublishTask, reused_id)
            assert unrelated_row is not None
            assert unrelated_row.source_intent_key.endswith("unrelated-id-reuse")
            assert int(second[0]["draft_task_id"]) != reused_id
            assert len(session.exec(select(XContentOpportunity)).all()) == 2
    finally:
        _restore(previous, tmp)


def test_political_sources_remain_analysis_only_and_never_become_drafts():
    previous, tmp = _init_tmp()
    try:
        with db.get_session() as session:
            account = DouyinAccount(
                platform="x", nickname="@s", sec_uid="s",
                storage_state="{}", status="active")
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = int(account.id)

        political = {
            "tweet_id": "political-1",
            "tweet_url": "https://x.com/p/status/political-1",
            "author_handle": "p",
            "author_name": "P",
            "text": "总统和政府政策对比，下一次选举应该怎么投票。",
            "view_count": 99999,
            "radar_score": 999,
            "exposure_efficiency": 99,
            "engagement_rate": 0.1,
            "trends": {},
        }
        tech = _items()[0].copy()
        tech["text"] = "新的 AI 工具更新了推理能力，我更关心真实工作流里能不能省时间。"
        digest = {
            "opportunities": [
                {
                    "title": "政府政策比较",
                    "angle": "围绕政府政策和选举展开",
                    "why": "政治帖曝光很高",
                    "evidence_tweet_ids": ["political-1"],
                },
                {
                    "title": "AI 工具工作流",
                    "angle": "从真实工作流效率切入",
                    "why": "工具类讨论在升温",
                    "evidence_tweet_ids": ["t1"],
                },
            ]
        }
        rows = asyncio.run(generate_and_persist_opportunities(
            account_id, 20, [political, tech], digest, {}, count=2))
        assert rows
        assert all("political-1" not in row["source_tweet_ids"] for row in rows)
        assert all("选举" not in row["draft_text"] for row in rows)
        assert all("政府政策" not in row["draft_text"] for row in rows)
    finally:
        _restore(previous, tmp)


def test_opportunity_api_uses_existing_scan_digest_and_creates_draft():
    previous, tmp = _init_tmp()
    try:
        with db.get_session() as session:
            account = DouyinAccount(
                platform="x", nickname="@s", sec_uid="s",
                storage_state="{}", status="active")
            session.add(account)
            session.commit()
            session.refresh(account)
            account_id = int(account.id)

            scan = XIntelScan(
                account_id=account_id,
                status="done",
                requested_accounts=1,
                successful_accounts=1,
                post_count=1,
                posts_per_account=5,
                finished_at=datetime.utcnow(),
                summary_json=json.dumps(_digest(), ensure_ascii=False),
                summary_source="rules",
                summary_generated_at=datetime.utcnow(),
            )
            session.add(scan)
            session.commit()
            session.refresh(scan)
            scan_id = int(scan.id)
            session.add(XIntelPostSnapshot(
                scan_id=scan_id,
                account_id=account_id,
                benchmark_id=None,
                tweet_id="t1",
                tweet_url="https://x.com/a/status/t1",
                author_handle="a",
                author_name="A",
                author_verified=True,
                author_followers=1000,
                text=_items()[0]["text"],
                posted_at="2026-09-30T02:00:00+00:00",
                view_count=12000,
                like_count=300,
                reply_count=60,
                retweet_count=80,
                engagement_rate=0.04,
                exposure_efficiency=12.0,
                radar_score=180.0,
            ))
            session.commit()

        result = asyncio.run(x_api.generate_intel_opportunities(
            x_api.XContentOpportunityGenerateIn(
                account_id=account_id, scan_id=scan_id, count=1)
        ))
        assert result["ok"] is True
        assert result["mode"] == "draft_only"
        assert result["count"] == 1
        assert result["items"][0]["draft_task_id"]

        listed = asyncio.run(x_api.list_intel_opportunities(account_id, 30))
        assert len(listed["items"]) == 1
        assert listed["items"][0]["source_tweet_ids"] == ["t1"]
    finally:
        _restore(previous, tmp)


def test_intel_automation_normalizes_auto_draft_settings():
    cfg = normalize_x_intel_automation({
        "enabled": True,
        "auto_opportunities_enabled": True,
        "auto_draft_count": 99,
    })
    assert cfg["auto_opportunities_enabled"] is True
    assert cfg["auto_draft_count"] == 6

    cfg = normalize_x_intel_automation({"auto_draft_count": 0})
    assert cfg["auto_opportunities_enabled"] is False
    assert cfg["auto_draft_count"] == 3


def test_unverified_personal_experience_is_detected():
    assert _has_unverified_personal_experience("我只要一开吃就停不下来") is True
    assert _has_unverified_personal_experience("我亲测这个工具三天") is True
    assert _has_unverified_personal_experience("我更关注它能不能真正落地") is False
    assert _has_unverified_personal_experience("准备后续实际测试，有结果再说") is False


def test_opportunity_ui_and_scheduler_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/x_intel.js").read_text(encoding="utf-8")
    monitor = (root / "app/engine/monitor.py").read_text(encoding="utf-8")

    assert "内容机会" in html
    assert 'id="x-intel-opportunity-table"' in html
    assert 'id="x-intel-auto-opportunities"' in html
    assert 'id="x-intel-auto-draft-count"' in html
    assert "/api/x/intel/opportunities/generate" in js
    assert "/api/x/intel/opportunities?account_id=" in js
    assert "generateXIntelOpportunities" in js
    assert "generate_intel_opportunities(" in monitor
    assert "auto_opportunities_enabled" in monitor
