import asyncio

from app.platforms.x.risk_probe import detect_x_write_risk, dismiss_x_benign_overlay


class _Node:
    def __init__(self, text):
        self.text = text
    async def count(self):
        return 1
    async def inner_text(self, timeout=3000):
        return self.text


class _Locator:
    def __init__(self, node):
        self.first = node


class _Page:
    def __init__(self, text):
        self.text = text
    def locator(self, _selector):
        return _Locator(_Node(self.text))


def test_detect_x_write_risk_matches_verification_marker():
    marker = asyncio.run(detect_x_write_risk(_Page("Please verify your identity to continue")))
    assert marker == "verify your identity"


def test_detect_x_write_risk_is_empty_on_normal_page():
    marker = asyncio.run(detect_x_write_risk(_Page("Home Timeline What's happening")))
    assert marker == ""


def test_reply_path_uses_shared_risk_probe_and_safe_mask_activation():
    source = open("app/platforms/x/client.py", encoding="utf-8").read()
    reply_block = source[source.index("async def reply_x") :]
    activation_block = source[source.index("async def _activate_x_control") :
                              source.index("async def _fill_editor")]
    assert "detect_x_write_risk(page)" in reply_block
    assert "_activate_x_control(" in reply_block
    assert "retry_before_boundary=True" in reply_block
    assert "force=True" not in reply_block
    assert "dismiss_x_benign_overlay(page)" in activation_block
    assert "detect_x_write_risk(page)" in activation_block
    assert "allow_mask_dom" in activation_block
    assert "if callable(before_activate) or not retry_before_boundary:" in activation_block


def test_publish_and_relationship_paths_use_shared_probe():
    client = open("app/platforms/x/client.py", encoding="utf-8").read()
    relationship = open("app/platforms/x/relationship.py", encoding="utf-8").read()
    assert "risk_blocked:X 发帖前检测到平台风控/验证提示" in client
    assert "risk_blocked:X {action} 前检测到平台风控/验证提示" in relationship
