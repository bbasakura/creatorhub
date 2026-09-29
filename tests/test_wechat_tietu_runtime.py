import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from app.browser.identity import Identity
from app.browser.manager import BrowserManager
from app.platforms.wechat_mp.tietu_runtime import topic_tokens


class TietuRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_topic_tokens_normalize_and_deduplicate(self):
        self.assertEqual(
            topic_tokens("#四大名著, 西游记  #四大名著，红楼梦"),
            ["#四大名著", "#西游记", "#红楼梦"],
        )

    async def test_resident_headed_context_reuses_same_account_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = BrowserManager("UA", directory, xhs_browser_mode="patchright")
            identity = Identity(
                account_id=7,
                profile_dir=str(Path(directory) / "acc_7"),
                identity_mode="native",
                platform="wechat_mp",
            )
            context = Mock()
            manager._launch_persistent = AsyncMock(return_value=context)

            first = await manager.resident_headed_context(identity)
            second = await manager.resident_headed_context(identity)

            self.assertIs(first, context)
            self.assertIs(second, context)
            manager._launch_persistent.assert_awaited_once_with(
                identity, headless=False)
            self.assertIn(identity.key, manager._headed_context_keys)
