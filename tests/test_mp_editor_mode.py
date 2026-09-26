import unittest
from unittest.mock import AsyncMock, Mock

from app.platforms.wechat_mp.publish import _is_tietu_editor


class TietuEditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_both_visible_controls(self):
        for absent in (None, "images", "body"):
            image = Mock()
            body = Mock()
            image.first.wait_for = AsyncMock(
                side_effect=TimeoutError() if absent == "images" else None)
            body.first.wait_for = AsyncMock(
                side_effect=TimeoutError() if absent == "body" else None)
            page = Mock()
            page.locator.side_effect = [image, body]
            with self.subTest(absent=absent):
                self.assertEqual(await _is_tietu_editor(page), absent is None)

    async def test_generic_article_editor_is_rejected(self):
        page = Mock()
        page.locator.return_value.first.wait_for = AsyncMock(side_effect=TimeoutError())
        self.assertFalse(await _is_tietu_editor(page))
