import asyncio
import tempfile
import unittest
from pathlib import Path

import app.db as db
from app.models import CommentTask, PublishTask
from app.platforms.x.client import detect_x_write_risk
from app.services.task_queue_actions import apply_queue_transition
from app.services.x_workflow import create_x_post_draft, create_x_reply_draft


class XDraftWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.previous_engine = db._engine
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(str(Path(self.tmp.name) / "x-drafts.db"))

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = self.previous_engine
        self.tmp.cleanup()

    def test_post_draft_is_durable_and_idempotent(self):
        first = create_x_post_draft(8, "hello X", intent_id="fixture-post")
        again = create_x_post_draft(8, "hello X", intent_id="fixture-post")
        self.assertTrue(first["draft"])
        self.assertEqual(first["task_id"], again["task_id"])
        self.assertTrue(again["idempotent_replay"])
        with db.get_session() as session:
            row = session.get(PublishTask, first["task_id"])
            self.assertEqual("x", row.platform)
            self.assertEqual("draft", row.status)
            apply_queue_transition(row, "publishes", "run-now")
            self.assertEqual("pending", row.status)

    def test_reply_draft_uses_comment_queue_and_semantic_dedupe(self):
        first = create_x_reply_draft(
            8, "https://x.com/example/status/1234567890", "具体回复",
            author_handle="@example", source_text="原帖正文")
        again = create_x_reply_draft(
            8, "1234567890", "具体回复", author_handle="example")
        self.assertEqual("comments", first["queue_type"])
        self.assertEqual(first["task_id"], again["task_id"])
        self.assertTrue(again["idempotent_replay"])
        with db.get_session() as session:
            row = session.get(CommentTask, first["task_id"])
            self.assertEqual("x", row.platform)
            self.assertEqual("1234567890", row.aweme_id)
            self.assertEqual("1234567890", row.target_comment_id)
            self.assertEqual("example", row.target_nick)
            self.assertEqual("draft", row.status)
            apply_queue_transition(row, "comments", "run-now")
            self.assertEqual("pending", row.status)


class _FakeNode:
    def __init__(self, text="", count=1):
        self._text = text
        self._count = count
        self.first = self

    async def count(self):
        return self._count

    async def inner_text(self, timeout=None):
        return self._text


class _FakePage:
    def __init__(self, body):
        self.body = body

    def locator(self, selector):
        if selector == "body":
            return _FakeNode(self.body)
        return _FakeNode("", 0)


def test_x_write_risk_probe_detects_platform_lock_signal():
    marker = asyncio.run(detect_x_write_risk(
        _FakePage("Your account is locked. Verify your identity to continue.")))
    assert marker in {"verify your identity", "account locked", "your account is locked"}


def test_x_worker_and_client_enforce_submit_boundary_contract():
    monitor = Path("app/engine/monitor.py").read_text(encoding="utf-8")
    client = Path("app/platforms/x/client.py").read_text(encoding="utf-8")
    assert "from ..platforms.x.client import (" in monitor
    assert "publish_x, reply_x" in monitor
    assert "await publish_x(" in monitor
    assert "await reply_x(" in monitor
    assert 'elif platform == "x":' in monitor
    assert "CommentTask, task_id" in monitor
    assert "on_submit=None" in client
    assert 'a[href*="/status/{tweet_id}"]' in client
    assert "detect_x_write_risk(page)" in client
