from pathlib import Path


def test_legacy_js_batch_runners_do_not_click_x_send_buttons():
    for path in (
        "app/platforms/x/runner_stream_batch.js",
        "app/platforms/x/runner_real_batch.js",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "sendBtn.click()" not in source
        assert "tweetButtonInline" not in source
        assert "enqueue-drafts" in source


def test_python_batch_replier_uses_durable_reply_drafts():
    source = Path("app/platforms/x/batch_replier.py").read_text(encoding="utf-8")
    assert "from app.services.x_workflow import create_x_reply_draft" in source
    assert "create_x_reply_draft(" in source
