import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlmodel import select
import app.db as db
from app.models import DouyinAccount, PublishTask
from app.services.d2y import enqueue_d2y, reconcile_d2y


class D2YEnqueueTests(unittest.TestCase):
    def setUp(self):
        self.previous = db._engine
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'hub.db'
        db.init_db(str(self.path))
        with db.get_session() as s:
            a = DouyinAccount(platform='youtube', status='active', sec_uid='fixture', credential_ref='fixture')
            s.add(a); s.commit(); s.refresh(a); self.account_id = a.id
        media = Path(self.tmp.name) / 'fixture.mp4'; media.write_bytes(b'fixture')
        self.videos = [dict(id=42, processed_path=str(media), title_en='fixture', desc_en='', tags_en='')]

    def tearDown(self):
        db._engine.dispose(); db._engine = self.previous; self.tmp.cleanup()

    def test_manifest_version_is_explicit_and_supported(self):
        result = enqueue_d2y(self.account_id, self.videos, manifest_version=1)
        self.assertEqual(1, result['manifest_version'])
        with self.assertRaisesRegex(ValueError, 'manifest_version'):
            enqueue_d2y(self.account_id, self.videos, manifest_version=2)

    def test_same_intent_rejects_changed_manifest_content(self):
        enqueue_d2y(self.account_id, self.videos, intent_id='stable')
        changed = [dict(self.videos[0], title_en='changed title')]
        with self.assertRaisesRegex(ValueError, 'intent conflict'):
            enqueue_d2y(self.account_id, changed, intent_id='stable')

    def test_reconcile_without_projector_never_imports_source_repository(self):
        enqueue_d2y(self.account_id, self.videos)
        with patch('app.services.d2y.source_adapter', side_effect=AssertionError('cross repo import')):
            self.assertEqual(1, reconcile_d2y())

    def test_retry_and_parallel_import_return_same_task(self):
        def run(_):
            return enqueue_d2y(self.account_id, self.videos)['tasks'][0]['task_id']
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(run, range(8)))
        self.assertEqual(1, len(set(ids)))
        with db.get_session() as s:
            self.assertEqual(1, len(s.exec(select(PublishTask)).all()))

    def test_projection_failure_is_replayable_without_new_task(self):
        first = enqueue_d2y(self.account_id, self.videos)
        def fail(_): raise sqlite3.OperationalError('injected commit failure')
        with self.assertRaises(sqlite3.OperationalError): reconcile_d2y(projector=fail)
        second = enqueue_d2y(self.account_id, self.videos)
        self.assertEqual(first['tasks'][0]['task_id'], second['tasks'][0]['task_id'])
        projected = []
        self.assertEqual(1, reconcile_d2y(projector=projected.extend))
        self.assertEqual(first['tasks'][0]['task_id'], projected[0]['task_id'])

    def test_uncertain_does_not_become_new_upload_on_retry(self):
        result = enqueue_d2y(self.account_id, self.videos)
        tid = result['tasks'][0]['task_id']
        with db.get_session() as s:
            t=s.get(PublishTask,tid);t.status='uncertain';s.add(t);s.commit()
        again = enqueue_d2y(self.account_id,self.videos)
        self.assertEqual(tid,again['tasks'][0]['task_id'])
        projected=[];reconcile_d2y(projector=projected.extend)
        self.assertEqual('uncertain',projected[0]['status'])

    def test_new_intent_allows_deliberate_republish(self):
        first=enqueue_d2y(self.account_id,self.videos)
        second=enqueue_d2y(self.account_id,self.videos,intent_id='manual-second-edition')
        self.assertNotEqual(first['tasks'][0]['task_id'],second['tasks'][0]['task_id'])

    def test_invalid_account_and_batch_fail_before_writes(self):
        with self.assertRaises(ValueError): enqueue_d2y(999,self.videos)
        with self.assertRaises(ValueError): enqueue_d2y(self.account_id,self.videos,interval_seconds=-1)
        with db.get_session() as s:self.assertEqual([],s.exec(select(PublishTask)).all())

    def test_old_database_recovers_indexes_and_intent_after_reopen(self):
        r=enqueue_d2y(self.account_id,self.videos);tid=r['tasks'][0]['task_id']
        with db._engine.begin() as c:
            c.execute(text('UPDATE publishtask SET source_intent_key=NULL'))
            c.execute(text('DROP INDEX ix_publishtask_content_fingerprint'))
            c.execute(text('DELETE FROM schema_migration'))
        db._engine.dispose();db.init_db(str(self.path));db._engine.dispose();db.init_db(str(self.path))
        indexes={i['name'] for i in inspect(db._engine).get_indexes('publishtask')}
        self.assertIn('ix_publishtask_content_fingerprint',indexes)
        self.assertEqual(tid,enqueue_d2y(self.account_id,self.videos)['tasks'][0]['task_id'])
        self.assertTrue(list((self.path.parent/'backups').glob('*.db')))


if __name__=='__main__':unittest.main()
