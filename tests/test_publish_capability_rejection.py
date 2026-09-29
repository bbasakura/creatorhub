import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import select

import app.db as db
from app.api.publish_contract import PublishIn
from app.main import add_publish
from app.models import DouyinAccount, PublishTask


class PublishCapabilityRejectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = db._engine
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(str(Path(self.tmp.name) / "capabilities.db"))

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = self.previous
        self.tmp.cleanup()

    def _account(self, platform: str) -> int:
        with db.get_session() as session:
            account = DouyinAccount(
                platform=platform, status="active",
                storage_state='{"cookies":[{"name":"fixture","value":"1","domain":"example.com","path":"/"}]}',
            )
            session.add(account); session.commit(); session.refresh(account)
            return account.id

    async def test_unsupported_draft_is_rejected_before_task_creation(self):
        for platform in ("xhs", "douyin", "kuaishou"):
            account_id = self._account(platform)
            body = PublishIn(account_id=account_id, media_type="images", operation="draft")
            with self.assertRaises(HTTPException) as raised:
                await add_publish(body)
            self.assertEqual(raised.exception.status_code, 400)
        with db.get_session() as session:
            self.assertEqual([], session.exec(select(PublishTask)).all())

    async def test_visibility_not_implemented_by_adapter_is_rejected(self):
        for platform in ("xhs", "kuaishou", "shipinhao"):
            account_id = self._account(platform)
            body = PublishIn(account_id=account_id, media_type="images", visibility="private")
            with self.assertRaises(HTTPException) as raised:
                await add_publish(body)
            self.assertEqual(raised.exception.status_code, 400)
        with db.get_session() as session:
            self.assertEqual([], session.exec(select(PublishTask)).all())


if __name__ == "__main__":
    unittest.main()
