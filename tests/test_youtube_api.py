import tempfile
import unittest
from pathlib import Path
import app.db as db
from app.main import PublishIn, add_publish
from app.models import DouyinAccount, PublishTask
from fastapi import HTTPException


class YoutubeApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = db._engine
        self.temp = tempfile.TemporaryDirectory()
        db.init_db(str(Path(self.temp.name)/'test.db'))
        self.video = Path(self.temp.name)/'video.mp4'
        self.video.write_bytes(b'video')
        with db.get_session() as session:
            account = DouyinAccount(platform='youtube',credential_ref='ref',sec_uid='channel')
            session.add(account); session.commit(); session.refresh(account)
            self.account = account.id

    def tearDown(self):
        db._engine.dispose(); db._engine = self.previous; self.temp.cleanup()

    async def test_defaults_private_and_rejects_duplicate(self):
        body = PublishIn(account_id=self.account, media_type='video', title='test',media_paths=[str(self.video)])
        result = await add_publish(body)
        self.assertEqual(result['visibility'],'private')
        with self.assertRaises(HTTPException) as raised:
            await add_publish(body)
        self.assertEqual(raised.exception.status_code,409)

    async def test_explicit_public_preserved(self):
        body = PublishIn(account_id=self.account,media_type='video',title='public',media_paths=[str(self.video)],visibility='public')
        result = await add_publish(body)
        self.assertEqual(result['visibility'],'public')

    async def test_schedule_rejected(self):
        body = PublishIn(account_id=self.account,media_type='video',title='test',media_paths=[str(self.video)],scheduled_at='2030-01-01T12:00')
        with self.assertRaises(HTTPException):
            await add_publish(body)

    def test_legacy_mp_operation_migrates(self):
        with db.get_session() as session:
            task = PublishTask(platform='wechat_mp',operation='publish')
            session.add(task); session.commit(); session.refresh(task); task_id=task.id
        path=Path(self.temp.name)/'test.db'
        db._engine.dispose(); db.init_db(str(path))
        with db.get_session() as session:
            self.assertEqual(session.get(PublishTask,task_id).operation,'draft')
