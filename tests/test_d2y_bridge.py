import tempfile
import unittest
import sqlite3
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, 'D:/soft/Codex/ai-narrator')
from src.douyin_to_youtube import d2y_to_creatorhub


class D2YBridgeTests(unittest.TestCase):
    def test_sync_result_updates_manifest(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute('''CREATE TABLE videos (
                id INTEGER PRIMARY KEY, status TEXT, youtube_video_id TEXT,
                published_at TEXT, error_msg TEXT, updated_at REAL
            )''')
            conn.execute("INSERT INTO videos (id, status) VALUES (999, 'processing')")
            conn.commit()
            conn.close()

            # Mock get_d2y_conn
            original_conn = d2y_to_creatorhub.get_d2y_conn
            d2y_to_creatorhub.get_d2y_conn = lambda: sqlite3.connect(db_path)
            try:
                d2y_to_creatorhub.sync_d2y_uploaded_result(999, 'test_yt_id', success=True)
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                row = cur.execute('SELECT status, youtube_video_id FROM videos WHERE id=999').fetchone()
                self.assertEqual(row[0], 'uploaded')
                self.assertEqual(row[1], 'test_yt_id')

                # Test failed sync
                d2y_to_creatorhub.sync_d2y_uploaded_result(999, '', success=False, error_msg='network error')
                row = cur.execute('SELECT status, error_msg FROM videos WHERE id=999').fetchone()
                self.assertEqual(row[0], 'failed')
                self.assertEqual(row[1], 'network error')
                conn.close()
            finally:
                d2y_to_creatorhub.get_d2y_conn = original_conn
        finally:
            try:
                Path(db_path).unlink()
            except Exception:
                pass
