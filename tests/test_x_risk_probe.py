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


def test_reply_path_dismisses_only_known_benign_overlay_after_risk_probe():
    source = open("app/platforms/x/client.py", encoding="utf-8").read()
    reply_block = source[source.index("async def reply_x") :]
    assert "detect_x_write_risk(page)" in reply_block
    assert "dismiss_x_benign_overlay(page)" in reply_block
    assert reply_block.index("detect_x_write_risk(page)") < reply_block.index("dismiss_x_benign_overlay(page)")


def test_publish_and_relationship_paths_use_shared_probe():
    client = open("app/platforms/x/client.py", encoding="utf-8").read()
    relationship = open("app/platforms/x/relationship.py", encoding="utf-8").read()
    assert "risk_blocked:X 发帖前检测到平台风控/验证提示" in client
    assert "risk_blocked:X {action} 前检测到平台风控/验证提示" in relationship
