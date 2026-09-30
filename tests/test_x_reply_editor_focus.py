import asyncio

import app.platforms.x.client as xclient
from app.platforms.x.client import _activate_x_control, _fill_editor, _last_visible_control


class _Editor:
    def __init__(self, visible, focus_failures=0):
        self.visible = visible
        self.value = ""
        self.focused = False
        self.clicked = False
        self.focus_failures = focus_failures
        self.focus_attempts = 0

    async def is_visible(self):
        return self.visible

    async def evaluate(self, _script):
        self.focus_attempts += 1
        if self.focus_failures:
            self.focus_failures -= 1
            raise RuntimeError("transient DOM focus failure")
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


class _Keyboard:
    def __init__(self, page):
        self.page = page
        self.presses = []
        self.insertions = []

    def _focused(self):
        return next((e for e in self.page.editors.editors if e.focused), None)

    async def press(self, key):
        self.presses.append(key)
        focused = self._focused()
        if focused and key == "Backspace":
            focused.value = ""

    async def insert_text(self, text):
        self.insertions.append(text)
        focused = self._focused()
        if not focused:
            raise RuntimeError("no focused editor")
        focused.value += text


class _Page:
    def __init__(self):
        self.bottom = _Editor(True)
        self.top = _Editor(True)
        self.editors = _Editors([self.bottom, self.top])
        self.keyboard = _Keyboard(self)

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
    assert page.keyboard.presses == ["Control+A"]
    assert page.keyboard.insertions == ["hello reply"]


def test_fill_editor_retries_dom_focus_without_pointer_click():
    page = _Page()
    page.top.focus_failures = 1
    editor = asyncio.run(_fill_editor(page, "retry reply"))
    assert editor is page.top
    assert page.top.focus_attempts == 3
    assert page.top.focused is True
    assert page.top.clicked is False
    assert page.top.value == "retry reply"
    assert page.keyboard.insertions == ["retry reply"]


class _Control:
    def __init__(self, visible=True, click_error=None):
        self.visible = visible
        self.click_error = click_error
        self.pointer_clicks = 0
        self.dom_clicks = 0

    async def is_visible(self):
        return self.visible

    async def click(self, timeout=4000):
        self.pointer_clicks += 1
        if self.click_error:
            raise self.click_error

    async def evaluate(self, _script):
        self.dom_clicks += 1


class _Controls:
    def __init__(self, controls):
        self.controls = controls

    async def count(self):
        return len(self.controls)

    def nth(self, index):
        return self.controls[index]


class _ControlScope:
    def __init__(self, controls):
        self.controls = _Controls(controls)

    def locator(self, _selector):
        return self.controls


def test_last_visible_control_prefers_last_visible_match():
    first = _Control(True)
    middle = _Control(False)
    last = _Control(True)
    picked = asyncio.run(_last_visible_control(
        _ControlScope([first, middle, last]), "button", timeout_ms=100))
    assert picked is last


def test_mask_submit_uses_dom_activation_and_marks_boundary_once(monkeypatch):
    async def no_risk(_page):
        return ""

    async def no_overlay(_page):
        return False

    async def has_mask(_page):
        return True

    monkeypatch.setattr(xclient, "detect_x_write_risk", no_risk)
    monkeypatch.setattr(xclient, "dismiss_x_benign_overlay", no_overlay)
    monkeypatch.setattr(xclient, "_visible_x_mask", has_mask)

    control = _Control(True)
    marks = []
    method = asyncio.run(_activate_x_control(
        object(), control, label="发送",
        before_activate=lambda: marks.append("submit"),
        allow_mask_dom=True,
    ))
    assert method == "dom"
    assert marks == ["submit"]
    assert control.dom_clicks == 1
    assert control.pointer_clicks == 0


def test_submit_boundary_pointer_failure_is_not_retried(monkeypatch):
    async def no_risk(_page):
        return ""

    async def no_overlay(_page):
        return False

    async def no_mask(_page):
        return False

    monkeypatch.setattr(xclient, "detect_x_write_risk", no_risk)
    monkeypatch.setattr(xclient, "dismiss_x_benign_overlay", no_overlay)
    monkeypatch.setattr(xclient, "_visible_x_mask", no_mask)

    control = _Control(True, click_error=RuntimeError("intercepted"))
    marks = []
    try:
        asyncio.run(_activate_x_control(
            object(), control, label="发送",
            before_activate=lambda: marks.append("submit"),
            retry_before_boundary=True,
            allow_mask_dom=True,
        ))
    except RuntimeError as exc:
        assert "intercepted" in str(exc)
    else:
        raise AssertionError("expected pointer activation failure")

    assert marks == ["submit"]
    assert control.pointer_clicks == 1
    assert control.dom_clicks == 0


def test_non_submit_control_does_not_dom_bypass_unknown_mask(monkeypatch):
    async def no_risk(_page):
        return ""

    async def no_overlay(_page):
        return False

    async def has_mask(_page):
        return True

    monkeypatch.setattr(xclient, "detect_x_write_risk", no_risk)
    monkeypatch.setattr(xclient, "dismiss_x_benign_overlay", no_overlay)
    monkeypatch.setattr(xclient, "_visible_x_mask", has_mask)

    control = _Control(True, click_error=RuntimeError("mask intercept"))
    try:
        asyncio.run(_activate_x_control(
            object(), control, label="打开回复框",
            retry_before_boundary=False,
            allow_mask_dom=False,
        ))
    except RuntimeError as exc:
        assert "mask intercept" in str(exc)
    else:
        raise AssertionError("expected blocked pointer click")
    assert control.dom_clicks == 0
