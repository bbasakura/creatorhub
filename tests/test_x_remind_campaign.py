import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app.api.x as x_api
import app.db as db
from app.models import CommentTask
from sqlmodel import select


class _FakeRemindManager:
    def __init__(self):
        self.state = {"targets": {}}

    def is_rate_limited(self):
        return False

    def get_summary(self):
        return {
            "status_distribution": {"confirmed_unreciprocated": 3},
            "reminded_waiting_24h": 0,
        }

    def get_confirmed_unreciprocated_targets(self, limit=5):
        rows = [
            {"clean_handle": "alpha", "nick": "Alpha"},
            {"clean_handle": "beta", "nick": "Beta"},
            {"clean_handle": "gamma", "nick": "Gamma"},
        ]
        return rows if limit is None else rows[:limit]


def test_remind_queue_offsets_are_immediate_worker_owned():
    offsets = [
        x_api._remind_schedule_offset(0, "alpha"),
        x_api._remind_schedule_offset(1, "beta"),
        x_api._remind_schedule_offset(2, "gamma"),
        x_api._remind_schedule_offset(3, "delta"),
    ]
    assert offsets == [0, 0, 0, 0]


def test_remind_start_enqueues_durable_comment_tasks_without_duplicate_restart():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "x-remind.db"))
        try:
            manager = _FakeRemindManager()
            with (
                patch.object(x_api, "UnreciprocatedManager", return_value=manager),
                patch.object(x_api, "_x_account", return_value=SimpleNamespace(id=8)),
                patch.object(x_api, "_runtime", return_value=(None, SimpleNamespace())),
            ):
                payload = asyncio.run(
                    x_api.remind_campaign_start(
                        x_api.XRemindCampaignIn(account_id=8)
                    )
                )
                assert payload["status"] == "queued"
                assert payload["queued"] == 3

                with db.get_session() as session:
                    rows = session.exec(
                        select(CommentTask)
                        .where(CommentTask.account_id == 8)
                        .order_by(CommentTask.id)
                    ).all()
                    assert len(rows) == 3
                    assert all(row.platform == "x" for row in rows)
                    assert all(row.status == "pending" for row in rows)
                    assert [row.xsec_token for row in rows] == [
                        "x_remind:alpha",
                        "x_remind:beta",
                        "x_remind:gamma",
                    ]
                    base = rows[0].scheduled_at
                    assert base is not None
                    gap_1 = (rows[1].scheduled_at - base).total_seconds()
                    gap_2 = (rows[2].scheduled_at - base).total_seconds()
                    assert abs(gap_1) < 1
                    assert abs(gap_2) < 1

                again = asyncio.run(
                    x_api.remind_campaign_start(
                        x_api.XRemindCampaignIn(account_id=8)
                    )
                )
                assert again["status"] == "already_running"

                with db.get_session() as session:
                    rows = session.exec(
                        select(CommentTask).where(CommentTask.account_id == 8)
                    ).all()
                    assert len(rows) == 3
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_remind_ui_and_worker_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/web/index.html").read_text(encoding="utf-8")
    js = (root / "app/web/app.js").read_text(encoding="utf-8")
    worker = (root / "app/engine/monitor.py").read_text(encoding="utf-8")
    relationship = (root / "app/platforms/x/relationship.py").read_text(encoding="utf-8")

    assert 'id="x-ops-remind-btn"' in html
    assert "runXHubTool('remind')" in html
    assert 'id="x-remind-status"' in html
    assert "startXRemindAll(triggerBtn = null)" in js
    assert "/api/x/remind/start" in js
    assert "/api/x/remind/status" in js
    assert "inspect_x_growth_profile(" in worker
    assert "mark_not_following(remind_handle)" in worker
    assert "mark_refollowed(" in worker
    assert "mark_no_tweets(remind_handle)" in worker
    assert "UnreciprocatedManager().record_reminded" in worker
    assert "trigger_rate_limit(15)" in worker
    assert "_X_REMIND_GAP_RANGE = (50, 70)" in worker
    assert "_X_VISIT_GAP_RANGE = (270, 330)" in worker
    assert '"follows_you": follows_you' in relationship
    assert '"latest_tweet_id": latest_tweet_id' in relationship
