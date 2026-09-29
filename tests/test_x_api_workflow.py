import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.api.x as x_api
from app.risk import OperationKind


class _Risk:
    def preflight(self, account_id, kind):
        assert kind == OperationKind.READ_LIGHT
        return SimpleNamespace(allowed=True, reason="")

    def record_success(self, account_id, kind):
        return None

    def record_failure(self, account_id, kind, exc):
        raise AssertionError(f"unexpected risk failure: {exc}")


class _Engine:
    def __init__(self):
        self.risk = _Risk()

    @asynccontextmanager
    async def operation_guard(self, account_id, kind, fallback_key=""):
        yield


class _Browser:
    def identity_for(self, account):
        return SimpleNamespace(key="fixture")


def _account():
    return SimpleNamespace(
        id=8, platform="x", status="active",
        storage_state='{"cookies": []}', creator_storage_state="")


def test_x_api_routes_include_read_preview_and_durable_drafts():
    paths = {route.path for route in x_api.router.routes}
    assert "/api/x/providers" in paths
    assert "/api/x/read/search" in paths
    assert "/api/x/read/mentions" in paths
    assert "/api/x/reply/preview" in paths
    assert "/api/x/post/draft" in paths
    assert "/api/x/reply/draft" in paths


def test_timeline_prefers_twikit_when_available():
    class Adapter:
        def __init__(self, states, **_kwargs):
            assert states

        async def timeline(self, *, count):
            return [{"id": "twikit-1"}]

    browser = _Browser()
    engine = _Engine()
    fallback = AsyncMock(return_value=[{"id": "browser-1"}])
    with patch.object(x_api, "_runtime", return_value=(browser, engine)), \
         patch.object(x_api, "_x_account", return_value=_account()), \
         patch.object(x_api, "TwikitReadAdapter", Adapter), \
         patch.object(x_api, "fetch_x_following_timeline", fallback):
        result = asyncio.run(x_api.timeline(8, 5))
    assert result["provider"] == "twikit"
    assert result["items"] == [{"id": "twikit-1"}]
    fallback.assert_not_awaited()


def test_timeline_falls_back_to_browser_on_twikit_failure():
    class BrokenAdapter:
        def __init__(self, states, **_kwargs):
            pass

        async def timeline(self, *, count):
            raise RuntimeError("twikit unavailable")

    browser = _Browser()
    engine = _Engine()
    fallback = AsyncMock(return_value=[{"id": "browser-1"}])
    with patch.object(x_api, "_runtime", return_value=(browser, engine)), \
         patch.object(x_api, "_x_account", return_value=_account()), \
         patch.object(x_api, "TwikitReadAdapter", BrokenAdapter), \
         patch.object(x_api, "fetch_x_following_timeline", fallback):
        result = asyncio.run(x_api.timeline(8, 5))
    assert result["provider"] == "browser"
    assert result["fallback_reason"] == "RuntimeError"
    assert result["items"] == [{"id": "browser-1"}]
    fallback.assert_awaited_once()
