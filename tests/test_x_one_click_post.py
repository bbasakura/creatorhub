import asyncio
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import app.api.x as x_api
import app.db as db
from app.models import DouyinAccount
from app.platforms.x.posting_engine import XPostingEngine
from app.services.x_post_campaign import (
    load_post_campaign,
    mark_post_queued,
    mark_post_success,
    post_campaign_due,
    start_post_campaign,
)


def _seed_account() -> int:
    with db.get_session() as session:
        account = DouyinAccount(
            platform="x",
            nickname="@sakurakk730",
            sec_uid="sakurakk730",
            status="active",
            storage_state='{"cookies":[{"name":"auth_token","value":"test"}]}',
            timezone_id="Asia/Shanghai",
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return int(account.id)


def test_reference_style_generator_is_short_natural_and_not_copy():
    refs = [
        "做自媒体别端着。\n说人话就行。\n#浇朋友",
        "今天继续干活。\n少想一点，多做一点。\n#蓝朋友",
        "成年人最重要的能力：\n该睡觉的时候睡觉。",
    ]
    text = XPostingEngine().generate_reference_style_post(
        refs, rng=random.Random(7))
    assert 1 <= len(text) <= 120
    assert text not in refs
    assert XPostingEngine.validate_post(text)["valid"] is True
    for phrase in ("首先", "其次", "综上所述", "值得注意的是", "赋能"):
        assert phrase not in text


def test_one_click_post_api_starts_persistent_target_campaign_without_eager_queue():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "one-click-post.db"))
        try:
            account_id = _seed_account()
            result = asyncio.run(x_api.one_click_post(
                x_api.XOneClickPostIn(account_id=account_id, target_count=3)))
            assert result["started"] is True
            assert result["state"]["enabled"] is True
            assert result["state"]["target_count"] == 3
            assert result["state"]["run_published"] == 0

            replay = asyncio.run(x_api.one_click_post(
                x_api.XOneClickPostIn(account_id=account_id, target_count=5)))
            assert replay["already_running"] is True
            assert replay["state"]["target_count"] == 3

            status = asyncio.run(x_api.one_click_post_status(account_id))
            assert status["state"]["target_count"] == 3
            assert status["active_tasks"] == []
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_post_campaign_counts_only_unique_successes_and_completes_at_target():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "post-campaign-state.db"))
        try:
            account_id = _seed_account()
            state = start_post_campaign(account_id, target_count=2)
            assert state["run_published"] == 0

            mark_post_queued(account_id, task_id=101, text="第一条")
            state = load_post_campaign(account_id)
            assert state["run_published"] == 0

            state = mark_post_success(
                account_id, task_id=101, text="第一条",
                result_url="https://x.com/a/status/101")
            assert state["run_published"] == 1
            assert state["enabled"] is True
            assert state["next_due_at"]
            due_at = datetime.fromisoformat(
                state["next_due_at"].replace("Z", "+00:00"))
            remaining = (due_at - datetime.now(timezone.utc)).total_seconds()
            assert 295 <= remaining <= 605
            assert post_campaign_due(state) is False
            first_due = state["next_due_at"]

            state = mark_post_success(
                account_id, task_id=101, text="第一条",
                result_url="https://x.com/a/status/101")
            assert state["run_published"] == 1
            assert state["next_due_at"] == first_due

            mark_post_queued(account_id, task_id=102, text="第二条")
            state = mark_post_success(
                account_id, task_id=102, text="第二条",
                result_url="https://x.com/a/status/102")
            assert state["run_published"] == 2
            assert state["enabled"] is False
            assert state["status"] == "completed"
            assert state["next_due_at"] == ""
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous
