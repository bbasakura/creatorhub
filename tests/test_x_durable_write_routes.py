import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.db as db
import app.api.x as x_api
from app.models import AccountActionTask
from app.platforms.x.relationship import set_x_following
from app.services.x_workflow import create_x_relationship_task


class _EmptyNode:
    first = None
    def __init__(self):
        self.first = self
    async def count(self):
        return 0
    async def is_visible(self):
        return False
    async def inner_text(self, timeout=None):
        return ""


class _FollowButton:
    first = None
    def __init__(self, page):
        self.page = page
        self.first = self
    async def count(self):
        return 1
    async def is_visible(self):
        return True
    async def click(self, timeout=None):
        raise RuntimeError("transport lost after submit boundary")


class _Page:
    url = "https://x.com/example"
    def __init__(self):
        self.follow = _FollowButton(self)
    def locator(self, _selector):
        return _EmptyNode()
    def get_by_role(self, _role, name=None):
        pattern = getattr(name, "pattern", "")
        if pattern.startswith("^(Follow|关注)"):
            return self.follow
        return _EmptyNode()
    async def wait_for_timeout(self, _ms):
        return None


class _Manager:
    def __init__(self):
        self.page = _Page()
    @asynccontextmanager
    async def visible_page(self, _identity, url=""):
        self.page.url = url
        yield self.page


def test_relationship_submit_callback_precedes_click_and_failure_is_uncertain():
    calls = []
    outcome = asyncio.run(set_x_following(
        _Manager(), SimpleNamespace(), "example", True,
        on_submit=lambda: calls.append("submitted")))
    assert calls == ["submitted"]
    assert outcome.status == "uncertain"
    assert outcome.changed is False


def test_growth_verified_gate_blocks_non_verified_profile_before_submit():
    calls = []
    outcome = asyncio.run(set_x_following(
        _Manager(), SimpleNamespace(), "example", True,
        on_submit=lambda: calls.append("submitted"),
        require_verified=True,
    ))
    assert outcome.status == "failed"
    assert "不是蓝V认证" in outcome.error
    assert calls == []


def test_relationship_task_is_durable_and_only_dedupes_active_attempts():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-actions.db"))
        try:
            first = create_x_relationship_task(8, "@example", "follow")
            again = create_x_relationship_task(8, "https://x.com/example", "follow")
            assert first["task_id"] == again["task_id"]
            assert again["idempotent_replay"] is True
            with db.get_session() as session:
                row = session.get(AccountActionTask, first["task_id"])
                assert row.status == "draft"
                row.status = "done"
                session.add(row); session.commit()
            later = create_x_relationship_task(8, "example", "follow")
            assert later["task_id"] != first["task_id"]
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_reply_api_uses_durable_comment_queue_not_direct_writer():
    engine = object()
    queue = AsyncMock(return_value={"ok": True, "status": "done"})
    draft = {
        "ok": True, "draft": True, "idempotent_replay": False,
        "queue_type": "comments", "task_id": 41, "status": "draft",
        "tweet_id": "123", "url": "https://x.com/i/web/status/123",
    }
    with patch.object(x_api, "_runtime", return_value=(object(), engine)), \
         patch.object(x_api, "_x_account", return_value=SimpleNamespace()), \
         patch.object(x_api, "create_x_reply_draft", return_value=draft), \
         patch.object(x_api, "perform_queue_action", queue):
        result = asyncio.run(x_api.send_reply(x_api.XReplyIn(
            account_id=8, tweet_ref="123", text="reply")))
    assert result["queued_via"] == "comments"
    queue.assert_awaited_once_with("comments", 41, "run-now", engine=engine)


def test_relationship_api_uses_durable_action_queue_not_direct_writer():
    engine = object()
    queue = AsyncMock(return_value={"ok": True, "status": "done"})
    task = {
        "ok": True, "idempotent_replay": False,
        "queue_type": "actions", "task_id": 42, "status": "draft",
        "action": "follow", "handle": "example", "url": "https://x.com/example",
    }
    with patch.object(x_api, "_runtime", return_value=(object(), engine)), \
         patch.object(x_api, "_x_account", return_value=SimpleNamespace()), \
         patch.object(x_api, "create_x_relationship_task", return_value=task), \
         patch.object(x_api, "perform_queue_action", queue):
        result = asyncio.run(x_api.relationship(x_api.XRelationshipIn(
            account_id=8, handle="example", action="follow")))
    assert result["queued_via"] == "actions"
    queue.assert_awaited_once_with("actions", 42, "run-now", engine=engine)


def test_x_api_has_no_direct_reply_or_relationship_writer_imports():
    source = Path("app/api/x.py").read_text(encoding="utf-8")
    assert "reply_x," not in source
    assert "set_x_following" not in source
    assert 'perform_queue_action(\n            "comments"' in source
    assert 'perform_queue_action(\n            "actions"' in source


def test_monitor_routes_x_relationship_actions_before_generic_follow_adapter():
    source = Path("app/engine/monitor.py").read_text(encoding="utf-8")
    start = source.index('if platform == "x" and action in {"follow", "unfollow"}:')
    generic = source.index('elif action == "follow":', start)
    branch = source[start:generic]
    assert "set_x_following(" in branch
    assert "do_follow(" not in branch
