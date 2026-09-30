from pathlib import Path

import pytest

from app.platforms.x.batch_replier import XBatchReplier


LEGACY_DELETE_SET = {
    "bottom_unfollow_pipeline.py",
    "fast_turbo_remind_pipeline.py",
    "follower_greeting_pipeline.py",
    "post_150_pipeline.py",
    "post_batch_pipeline.py",
    "post_50_manager.py",
    "step_greeter.py",
    "step_poster.py",
    "step_remind_confirmed.py",
    "step_unfollower.py",
    "unfollow_pipeline.py",
}


def test_only_monitor_worker_may_call_low_level_x_writers():
    allowed = {
        Path("app/engine/monitor.py"),
        Path("app/platforms/x/client.py"),
        Path("app/platforms/x/relationship.py"),
    }
    forbidden_calls = ("publish_x(", "reply_x(", "set_x_following(")
    offenders = []
    for root in (Path("app"), Path("scripts")):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".js"} or path in allowed:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if any(call in source for call in forbidden_calls):
                offenders.append(str(path))
    assert offenders == []


def test_removed_legacy_x_state_machines_stay_removed():
    root = Path("app/platforms/x")
    remaining = sorted(path.name for path in root.iterdir() if path.name in LEGACY_DELETE_SET)
    assert remaining == []


def test_legacy_js_runners_are_fused_or_queue_only():
    for path in (
        Path("app/platforms/x/cron_remind_runner.js"),
        Path("app/platforms/x/runner_unreciprocated_direct.js"),
        Path("app/platforms/x/runner_concurrent_tabs.js"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "legacy_direct_x_write_disabled" in source
        assert "tweetButtonInline" not in source
        assert "confirmationSheetConfirm" not in source

    for path in (
        Path("app/platforms/x/runner_real_batch.js"),
        Path("app/platforms/x/runner_stream_batch.js"),
        Path("app/platforms/x/runner_unreciprocated.js"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "enqueue-drafts" in source
        assert "tweetButtonInline" not in source
        assert "confirmationSheetConfirm" not in source


def test_queue_acceptance_cannot_stamp_legacy_reply_success():
    with pytest.raises(RuntimeError, match="success stamping is disabled"):
        XBatchReplier().record_success("n", "@h", "https://x.com/h/status/1", "src", "reply")


def test_no_tmp_x_artifacts_left_in_project_root():
    assert sorted(Path(".").glob(".tmp_x_*")) == []
