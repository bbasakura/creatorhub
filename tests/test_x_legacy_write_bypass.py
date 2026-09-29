from pathlib import Path

from app.platforms.x.browser_ops import XBrowserOps
from app.platforms.x.runner import XRunner


def test_legacy_browser_ops_cannot_emit_clicking_writer_code():
    ops = XBrowserOps()
    reply = ops.get_reply_workflow_code("123", "reply")
    post = ops.get_post_workflow_code("post")
    for source in (reply, post):
        assert "disabled" in source
        assert "tweetButtonInline" not in source
        assert ".click()" not in source


def test_legacy_runner_plans_only_durable_queue_paths():
    runner = XRunner()
    post = runner.plan_next_post("pain_point")
    reply = runner.plan_reply("自动化最难的是幂等和恢复吗？", "tester", "@tester", "https://x.com/tester/status/123")
    assert post["write_path"] == "/api/x/post/draft"
    assert post["requires_task_queue"] is True
    assert reply["write_path"] == "/api/x/reply/draft"
    assert reply["requires_task_queue"] is True
    assert "inject_code" not in post
    assert "inject_code" not in reply


def test_legacy_runner_sources_have_no_x_send_button_clicks():
    paths = [
        Path("app/platforms/x/browser_ops.py"),
        Path("app/platforms/x/runner.py"),
        *sorted(Path("app/platforms/x").glob("*.js")),
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "sendBtn.click()" not in source, path
        assert "postBtn.click()" not in source, path
        assert "tweetButtonInline" not in source, path


def test_unreciprocated_runner_is_dry_run_or_durable_draft_only_when_present():
    runner_path = Path("app/platforms/x/runner_unreciprocated.js")
    cron_path = Path("app/platforms/x/cron_remind_runner.js")
    if not runner_path.exists() or not cron_path.exists():
        return
    runner = runner_path.read_text(encoding="utf-8")
    cron = cron_path.read_text(encoding="utf-8")
    assert "enqueue-drafts" in runner
    assert "dry_run_requires_account_id" in runner
    assert "accountId = null" in runner
    assert "accountId = null" in cron
