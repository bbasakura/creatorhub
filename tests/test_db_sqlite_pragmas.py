import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect

import app.db as db


class SqlitePragmaTests(unittest.TestCase):
    def test_init_db_enables_reliability_pragmas_and_task_event_table(self):
        old_engine = db._engine
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "creatorhub-test.db"
            engine = db.init_db(str(path))
            try:
                with engine.connect() as conn:
                    journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
                    foreign_keys = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
                    busy_timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
                    synchronous = conn.exec_driver_sql("PRAGMA synchronous").scalar()
                self.assertEqual(str(journal_mode).lower(), "wal")
                self.assertEqual(foreign_keys, 1)
                self.assertGreaterEqual(busy_timeout, 10000)
                self.assertEqual(synchronous, 1)  # NORMAL
                self.assertTrue(inspect(engine).has_table("taskevent"))
            finally:
                engine.dispose()
                db._engine = old_engine


if __name__ == "__main__":
    unittest.main()
