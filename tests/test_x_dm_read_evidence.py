import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.platforms.x.client import fetch_x_dm_conversations


def test_missing_conversation_selectors_do_not_report_verified_empty_inbox():
    page = SimpleNamespace(
        wait_for_timeout=AsyncMock(),
        locator=lambda selector: SimpleNamespace(count=AsyncMock(return_value=0)),
    )

    class Manager:
        @asynccontextmanager
        async def visible_page(self, identity, **kwargs):
            yield page

    with patch("app.platforms.x.client._page_logged_out", AsyncMock(return_value=False)):
        with pytest.raises(RuntimeError, match="尚未确认空收件箱"):
            asyncio.run(fetch_x_dm_conversations(Manager(), object()))
