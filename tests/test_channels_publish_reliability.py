from pathlib import Path


def test_channels_requires_positive_draft_receipt():
    source = Path("app/platforms/channels/publish.py").read_text(encoding="utf-8")
    assert "if saved:" in source
    assert "未观察到明确保存回执" in source
    assert "write_uncertain:" in source


def test_channels_never_uses_button_disappearance_as_publish_success():
    source = Path("app/platforms/channels/publish.py").read_text(encoding="utf-8")
    assert "not await pub.count() or not await pub.is_visible()" not in source
    assert "按钮消失本身不是成功证据" in source
