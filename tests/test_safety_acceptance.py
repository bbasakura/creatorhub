import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import inspect
from starlette.requests import Request

import app.db as db
import app.main as main
from app.models import DouyinAccount, PublishTask


def request_from(host: str) -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": (host, 43210),
        "server": ("127.0.0.1", 18888),
    })


class YoutubeSafetyApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_db = db._engine
        self.previous_main_engine = main.engine
        self.temp = tempfile.TemporaryDirectory()
        db.init_db(str(Path(self.temp.name) / "youtube-safety.db"))
        main.engine = None
        with db.get_session() as session:
            account = DouyinAccount(
                platform="youtube", nickname="channel", status="active",
                credential_ref="credential", sec_uid="channel-id",
            )
            session.add(account); session.commit(); session.refresh(account)
            self.account_id = account.id

    def tearDown(self):
        main.engine = self.previous_main_engine
        if db._engine is not None:
            db._engine.dispose()
        db._engine = self.previous_db
        self.temp.cleanup()

    def test_remote_resume_and_disconnect_are_forbidden(self):
        remote = request_from("10.20.30.40")
        with self.assertRaises(HTTPException) as resume:
            asyncio.run(main.youtube_resume(1, remote))
        with self.assertRaises(HTTPException) as disconnect:
            asyncio.run(main.youtube_disconnect(self.account_id, remote))
        self.assertEqual(resume.exception.status_code, 403)
        self.assertEqual(disconnect.exception.status_code, 403)

    def test_resume_requires_existing_upload_session_and_reuses_task(self):
        with db.get_session() as session:
            task = PublishTask(
                platform="youtube", account_id=self.account_id,
                media_type="video", status="uncertain", error="write_uncertain:test",
            )
            session.add(task); session.commit(); session.refresh(task)
            task_id = task.id
        with patch.dict(os.environ, {"CREATORHUB_ADMIN_TOKEN": ""}), \
                patch("app.platforms.youtube.client.load", return_value={
                    "session": "https://www.googleapis.com/upload-session"
                }):
            result = asyncio.run(main.youtube_resume(task_id, request_from("127.0.0.1")))
        self.assertTrue(result["ok"])
        with db.get_session() as session:
            task = session.get(PublishTask, task_id)
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.error, "")

    def test_resume_without_upload_session_stays_blocked(self):
        with db.get_session() as session:
            task = PublishTask(
                platform="youtube", account_id=self.account_id,
                media_type="video", status="uncertain",
            )
            session.add(task); session.commit(); session.refresh(task)
            task_id = task.id
        with patch.dict(os.environ, {"CREATORHUB_ADMIN_TOKEN": ""}), \
                patch("app.platforms.youtube.client.load", side_effect=FileNotFoundError):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(main.youtube_resume(task_id, request_from("127.0.0.1")))
        self.assertEqual(caught.exception.status_code, 409)
        with db.get_session() as session:
            self.assertEqual(session.get(PublishTask, task_id).status, "uncertain")

    def test_disconnect_rejects_active_upload(self):
        with db.get_session() as session:
            session.add(PublishTask(
                platform="youtube", account_id=self.account_id,
                media_type="video", status="publishing"))
            session.commit()
        with patch.dict(os.environ, {"CREATORHUB_ADMIN_TOKEN": ""}):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(main.youtube_disconnect(
                    self.account_id, request_from("127.0.0.1")))
        self.assertEqual(caught.exception.status_code, 409)


class PlatformCircuitApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_db = db._engine
        self.previous_main_engine = main.engine
        self.temp = tempfile.TemporaryDirectory()
        db.init_db(str(Path(self.temp.name) / "circuit-api.db"))
        main.engine = None

    def tearDown(self):
        main.engine = self.previous_main_engine
        if db._engine is not None:
            db._engine.dispose()
        db._engine = self.previous_db
        self.temp.cleanup()

    def test_open_list_and_clear_platform_circuit(self):
        req = request_from("127.0.0.1")
        with patch.dict(os.environ, {"CREATORHUB_ADMIN_TOKEN": ""}):
            opened = asyncio.run(main.open_platform_risk_circuit(
                "youtube",
                main.PlatformCircuitIn(
                    confirmed=True, reason="系统性写入异常", duration_seconds=600),
                req,
            ))
            rows = asyncio.run(main.list_platform_risk_circuits())
            cleared = asyncio.run(main.clear_platform_risk_circuit(
                "youtube", main.RiskClearIn(confirmed=True, reason="人工核验恢复"), req))
        self.assertTrue(opened["ok"])
        self.assertEqual(rows[0]["platform"], "youtube")
        self.assertTrue(rows[0]["is_open"])
        self.assertTrue(cleared["cleared"])


class LegacyDatabaseMigrationTests(unittest.TestCase):
    def test_minimal_old_publish_table_is_backed_up_and_upgraded(self):
        previous = db._engine
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            con = sqlite3.connect(path)
            try:
                con.execute("CREATE TABLE publishtask (id INTEGER PRIMARY KEY)")
                con.execute("INSERT INTO publishtask(id) VALUES (1)")
                con.commit()
            finally:
                con.close()
            engine = db.init_db(str(path))
            try:
                columns = {item["name"] for item in inspect(engine).get_columns("publishtask")}
                self.assertIn("source_intent_key", columns)
                self.assertIn("content_fingerprint", columns)
                self.assertTrue(inspect(engine).has_table("taskevent"))
                self.assertTrue(inspect(engine).has_table("platformriskcircuit"))
                with engine.connect() as conn:
                    self.assertEqual(
                        conn.exec_driver_sql("SELECT COUNT(*) FROM schema_migration WHERE version=1").scalar(), 1)
                backups = list((path.parent / "backups").glob("legacy-before-v1-*.db"))
                self.assertEqual(len(backups), 1)
            finally:
                engine.dispose()
                db._engine = previous


if __name__ == "__main__":
    unittest.main()
