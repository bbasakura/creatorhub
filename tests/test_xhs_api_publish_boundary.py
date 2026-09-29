from pathlib import Path
from unittest.mock import patch

from app.platforms.xhs import publish as publish_module


class _FakeApi:
    def __init__(self, *_args, **_kwargs):
        pass
    def close(self):
        pass
    def post_note(self, **kwargs):
        kwargs["on_submit"]()
        raise RuntimeError("connection lost after note POST started")


def test_xhs_api_post_calls_submit_boundary_before_final_note_request():
    source = Path("app/platforms/xhs/creator_api.py").read_text(encoding="utf-8")
    marker = source.index("if callable(on_submit):")
    request = source.index("self.cli.post(EDITH_URL + post_api")
    assert marker < request


def test_xhs_api_transport_loss_after_submit_is_uncertain(tmp_path):
    media = tmp_path / "one.jpg"
    media.write_bytes(b"fixture")
    calls = []
    with patch("app.platforms.xhs.creator_api.XhsCreatorApi", _FakeApi):
        ok, url, err = publish_module._publish_api_sync(
            "a1=fixture", "image", "标题", "正文", [str(media)], [],
            on_submit=lambda: calls.append("submitted"))
    assert calls == ["submitted"]
    assert ok is False
    assert url == ""
    assert err.startswith("write_uncertain:")
    assert "禁止自动重试" in err


def test_xhs_monitor_supplies_submit_boundary_for_api_and_browser_modes():
    source = Path("app/engine/monitor.py").read_text(encoding="utf-8")
    window = source[source.index("xhs_mode ="):source.index("return await self._finish_publish(task_id, ok, url, err)", source.index("xhs_mode ="))]
    assert 'if xhs_mode == "browser" else None' not in window
    assert "on_submit=lambda: self._mark_browser_submit(" in window
