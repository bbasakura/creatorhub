import unittest
from datetime import datetime

from sqlmodel import SQLModel, Session, create_engine

from app.api.publish_contract import PublishIn, publish_fingerprint, publish_intent_key
from app.models import PublishTask
from app.services.publish_idempotency import (
    PublishIntentConflict,
    persist_direct_publish,
    refresh_direct_publish_identity,
)


class PublishFingerprintTests(unittest.TestCase):
    def test_fingerprint_covers_publish_semantics(self):
        base = PublishIn(account_id=7, media_type="video", title=" hello ",
                         media_paths=[r"D:\\media\\a.mp4"], visibility="public")
        first = publish_fingerprint(base, platform="douyin", visibility="public",
                                    operation="publish", scheduled_at=None)
        same = publish_fingerprint(base, platform="douyin", visibility="public",
                                   operation="publish", scheduled_at=None)
        private = publish_fingerprint(base, platform="douyin", visibility="private",
                                      operation="publish", scheduled_at=None)
        scheduled = publish_fingerprint(base, platform="douyin", visibility="public",
                                        operation="publish", scheduled_at=datetime(2026, 9, 27))
        self.assertEqual(first, same)
        self.assertNotEqual(first, private)
        self.assertNotEqual(first, scheduled)

    def test_intent_key_modes(self):
        body = PublishIn(account_id=3, intent_id="request_1")
        self.assertEqual(publish_intent_key(body, "abc"), "publish:3:client:request_1")
        auto = PublishIn(account_id=3)
        self.assertEqual(publish_intent_key(auto, "abc"), "publish:3:fp:abc")
        duplicate = PublishIn(account_id=3, allow_duplicate=True)
        self.assertIsNone(publish_intent_key(duplicate, "abc"))


class PublishPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)

    def test_explicit_intent_replays_existing_row(self):
        with Session(self.engine) as session:
            first = PublishTask(account_id=1, platform="douyin",
                                content_fingerprint="fp", source_intent_key="publish:1:client:x")
            saved, replay = persist_direct_publish(session, first, explicit_intent=True)
            self.assertFalse(replay)
            second = PublishTask(account_id=1, platform="douyin",
                                 content_fingerprint="fp", source_intent_key="publish:1:client:x")
            existing, replay = persist_direct_publish(session, second, explicit_intent=True)
            self.assertTrue(replay)
            self.assertEqual(existing.id, saved.id)

    def test_same_auto_intent_requires_original_task_or_allow_duplicate(self):
        with Session(self.engine) as session:
            first = PublishTask(account_id=1, platform="douyin",
                                content_fingerprint="fp", source_intent_key="publish:1:fp:fp")
            persist_direct_publish(session, first)
            with self.assertRaises(PublishIntentConflict):
                persist_direct_publish(session, PublishTask(
                    account_id=1, platform="douyin", content_fingerprint="fp",
                    source_intent_key="publish:1:fp:fp"))

    def test_explicit_intent_cannot_change_payload(self):
        with Session(self.engine) as session:
            persist_direct_publish(session, PublishTask(
                account_id=1, platform="douyin", content_fingerprint="fp-a",
                source_intent_key="publish:1:client:x"), explicit_intent=True)
            with self.assertRaises(PublishIntentConflict):
                persist_direct_publish(session, PublishTask(
                    account_id=1, platform="douyin", content_fingerprint="fp-b",
                    source_intent_key="publish:1:client:x"), explicit_intent=True)


    def test_edit_refreshes_auto_intent_key(self):
        with Session(self.engine) as session:
            task = PublishTask(account_id=1, platform="douyin",
                               content_fingerprint="old",
                               source_intent_key="publish:1:fp:old")
            session.add(task); session.commit(); session.refresh(task)
            changed = refresh_direct_publish_identity(session, task, "new")
            session.add(task); session.commit(); session.refresh(task)
            self.assertTrue(changed)
            self.assertEqual(task.content_fingerprint, "new")
            self.assertEqual(task.source_intent_key, "publish:1:fp:new")
            self.assertEqual(task.source_revision, 1)

    def test_edit_detects_auto_intent_collision(self):
        with Session(self.engine) as session:
            first = PublishTask(account_id=1, platform="douyin",
                                content_fingerprint="target",
                                source_intent_key="publish:1:fp:target")
            second = PublishTask(account_id=1, platform="douyin",
                                 content_fingerprint="old",
                                 source_intent_key="publish:1:fp:old")
            session.add(first); session.add(second); session.commit(); session.refresh(second)
            with self.assertRaises(PublishIntentConflict):
                refresh_direct_publish_identity(session, second, "target")

    def test_edit_rejects_explicit_intent_semantic_change(self):
        with Session(self.engine) as session:
            task = PublishTask(account_id=1, platform="douyin",
                               content_fingerprint="old",
                               source_intent_key="publish:1:client:req")
            session.add(task); session.commit(); session.refresh(task)
            with self.assertRaises(PublishIntentConflict):
                refresh_direct_publish_identity(session, task, "new")

    def test_source_owned_intent_is_preserved(self):
        with Session(self.engine) as session:
            task = PublishTask(account_id=1, platform="youtube", source_platform="d2y",
                               content_fingerprint="source-fp",
                               source_intent_key="d2y:1:9:upload:initial")
            session.add(task); session.commit(); session.refresh(task)
            changed = refresh_direct_publish_identity(session, task, "ignored")
            session.add(task); session.commit(); session.refresh(task)
            self.assertFalse(changed)
            self.assertEqual(task.content_fingerprint, "source-fp")
            self.assertEqual(task.source_intent_key, "d2y:1:9:upload:initial")
            self.assertEqual(task.source_revision, 1)


if __name__ == "__main__":
    unittest.main()
