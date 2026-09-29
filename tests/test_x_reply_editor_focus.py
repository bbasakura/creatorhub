import asyncio

from app.platforms.x.client import _fill_editor


class _Editor:
    def __init__(self, visible):
        self.visible = visible
        self.value = ""
        self.focused = False
        self.clicked = False

    async def is_visible(self):
        return self.visible

    async def evaluate(self, _script):
        self.focused = True

    async def click(self, timeout=3000):
        self.clicked = True
        raise AssertionError("mouse click should not be required")

    async def fill(self, text):
        self.value = text

    async def inner_text(self):
        return self.value


class _Editors:
    def __init__(self, editors):
        self.editors = editors

    async def count(self):
        return len(self.editors)

    def nth(self, index):
        return self.editors[index]


class _Page:
    def __init__(self):
        self.bottom = _Editor(True)
        self.top = _Editor(True)
        self.editors = _Editors([self.bottom, self.top])

    def locator(self, selector):
        assert selector == '[data-testid="tweetTextarea_0"]'
        return self.editors

    async def wait_for_timeout(self, _ms):
        return None


def test_fill_editor_prefers_topmost_visible_editor_and_dom_focus():
    page = _Page()
    editor = asyncio.run(_fill_editor(page, "hello reply"))
    assert editor is page.top
    assert page.top.focused is True
    assert page.top.clicked is False
    assert page.top.value == "hello reply"
    assert page.bottom.value == ""
