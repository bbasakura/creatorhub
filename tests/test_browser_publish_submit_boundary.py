from pathlib import Path


def test_browser_publish_adapters_expose_submit_boundary_callback():
    files = {
        "x": Path("app/platforms/x/client.py").read_text(encoding="utf-8"),
        "douyin": Path("app/platforms/douyin/publish.py").read_text(encoding="utf-8"),
        "kuaishou": Path("app/platforms/kuaishou/publish.py").read_text(encoding="utf-8"),
        "shipinhao": Path("app/platforms/channels/publish.py").read_text(encoding="utf-8"),
    }
    for platform, source in files.items():
        assert "on_submit=None" in source, platform
        assert "if callable(on_submit):" in source, platform
        assert "on_submit()" in source, platform


def test_monitor_persists_submit_boundary_for_all_browser_publishers():
    source = Path("app/engine/monitor.py").read_text(encoding="utf-8")
    assert "topics=topics,\n                    on_submit=lambda: self._mark_browser_submit(" in source
    assert "topics=topics, headed=True,\n                                                      on_submit=lambda: self._mark_browser_submit(" in source
    assert "operation=operation,\n                                                      on_submit=lambda: self._mark_browser_submit(" in source
    assert "collection_name=collection_name,\n                                                    on_submit=lambda: self._mark_browser_submit(" in source


def test_browser_publishers_fail_uncertain_after_submit_boundary():
    for path in (
        "app/platforms/douyin/publish.py",
        "app/platforms/kuaishou/publish.py",
        "app/platforms/channels/publish.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "write_uncertain:" in source
        assert "禁止自动重试" in source


def test_submit_boundary_does_not_retry_final_click():
    douyin = Path("app/platforms/douyin/publish.py").read_text(encoding="utf-8")
    channels = Path("app/platforms/channels/publish.py").read_text(encoding="utf-8")
    assert "_click_first(page, _PUBLISH_BTN, timeout=4000)" not in douyin[douyin.index('if callable(on_submit):'):]
    assert 'pub.evaluate("el => el.click()")' not in channels
