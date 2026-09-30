import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.db as db
import app.api.x as x_api
from app.models import CommentTask, DouyinAccount, FollowEdge
from app.platforms.x.agent_reach import AgentReachReadAdapter


def test_agent_reach_user_posts_filters_retweets_and_keeps_original_posts():
    adapter = AgentReachReadAdapter("sakurakk730", command="twitter")
    payload = {
        "data": [
            {
                "id": "1", "text": "转发", "isRetweet": True,
                "author": {"screenName": "alice"},
            },
            {
                "id": "2", "text": "原创内容", "isRetweet": False,
                "author": {"screenName": "alice", "name": "Alice"},
                "createdAtISO": "2026-09-30T00:00:00+00:00",
            },
        ]
    }
    with patch.object(adapter, "_assert_account", AsyncMock(return_value={})),          patch.object(adapter, "_run_json", AsyncMock(return_value=payload)) as run:
        rows = asyncio.run(adapter.user_posts("alice", count=3))
    assert [row["id"] for row in rows] == ["2"]
    run.assert_awaited_once_with(["user-posts", "alice", "-n", "3", "--json"])


def test_visit_batch_creates_drafts_and_skips_recent_interaction():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-visits.db"))
        try:
            with db.get_session() as session:
                account = DouyinAccount(
                    platform="x", nickname="@sakurakk730", sec_uid="sakurakk730",
                    storage_state="{}", status="active")
                session.add(account); session.commit(); session.refresh(account)
                alice = FollowEdge(
                    platform="x", account_id=account.id, direction="fan",
                    uid="alice", sec_uid="alice", nickname="Alice")
                bob = FollowEdge(
                    platform="x", account_id=account.id, direction="fan",
                    uid="bob", sec_uid="bob", nickname="Bob")
                session.add(alice); session.add(bob); session.commit()
                session.refresh(alice); session.refresh(bob)
                session.add(CommentTask(
                    platform="x", account_id=account.id,
                    aweme_id="old-bob", target_nick="bob",
                    target_text="old", content="old reply",
                    status="done", done_at=datetime.now(timezone.utc).replace(tzinfo=None)))
                session.commit()
                account_id = account.id
                alice_id, bob_id = alice.id, bob.id

            class FakeAdapter:
                def __init__(self):
                    self.calls = []
                async def user_posts(self, handle, count=3):
                    self.calls.append(handle)
                    tweet_id = "2105078394866323630" if handle == "alice" else "2105078394866323631"
                    return [{
                        "id": tweet_id,
                        "url": f"https://x.com/{handle}/status/{tweet_id}",
                        "text": "今天把数据管道重构了一遍，终于顺了",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "author": {"handle": handle, "name": handle},
                        "metrics": {},
                    }]

            adapter = FakeAdapter()
            decision = SimpleNamespace(
                eligible=True, reply="这下顺多了，重构完最舒服的就是后面省心。",
                source="model", reason="ok", score=8)
            body = x_api.XVisitDraftBatchIn(
                account_id=account_id,
                edge_ids=[alice_id, bob_id],
                mode="content",
                threshold=4,
                skip_recent_hours=24,
                max_post_age_days=30,
            )
            with patch.object(x_api, "_agent_reach_adapter", return_value=adapter),                  patch.object(x_api, "decide_reply", AsyncMock(return_value=decision)),                  patch.object(x_api, "get_setting", return_value="0"):
                result = asyncio.run(x_api.create_visit_drafts(body))

            assert result["draft_only"] is True
            assert result["created"] == 1
            assert result["skipped"] == 1
            assert adapter.calls == ["alice"]
            with db.get_session() as session:
                drafts = session.query(CommentTask).filter(
                    CommentTask.platform == "x",
                    CommentTask.account_id == account_id,
                    CommentTask.status == "draft",
                ).all()
                assert len(drafts) == 1
                assert drafts[0].target_nick == "alice"
                assert drafts[0].aweme_id == "2105078394866323630"
                assert "重构" in drafts[0].target_text
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_visit_endpoint_is_draft_only_and_has_no_direct_writer_call():
    source = Path("app/api/x.py").read_text(encoding="utf-8")
    visit = source[source.index('@router.post("/visit/drafts")'):]
    visit = visit[:visit.index("class XRelationshipIn")]
    assert "create_x_reply_draft(" in visit
    assert "reply_x(" not in visit
    assert "perform_queue_action(" not in visit


def test_visit_ui_lives_in_ops_not_fan_page_and_remains_draft_only():
    index = Path("app/web/index.html").read_text(encoding="utf-8")
    js = Path("app/web/app.js").read_text(encoding="utf-8")
    assert 'id="x-visit-mode"' in index
    assert 'class="x-ops-action visit"' in index
    assert "runXHubTool('visit')" in index
    assert 'id="x-fan-visit-drafts"' not in index
    fans_start = index.index('data-hubpanel="fans"')
    dm_start = index.index('data-hubpanel="dm"')
    fans_html = index[fans_start:dm_start]
    assert "生成串门草稿" not in fans_html
    assert "串门文案模式" not in fans_html
    assert "generateXVisitDrafts" in js
    assert 'api("/api/x/visit/drafts"' in js
    assert "本操作只生成评论草稿，不会直接发送到 X" in js
