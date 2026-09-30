import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.platforms.x.twikit_client import (
    TwikitAuthUnavailable,
    TwikitReadAdapter,
    TwikitUnavailable,
    cookies_from_storage_states,
    has_twikit_auth,
    resolve_twikit_proxy,
)
from app.platforms.x.providers import x_provider_status


def _state():
    return json.dumps({"cookies": [
        {"name": "auth_token", "value": "secret-a", "domain": ".x.com", "path": "/"},
        {"name": "ct0", "value": "secret-b", "domain": ".x.com", "path": "/"},
        {"name": "foreign", "value": "nope", "domain": ".example.com", "path": "/"},
    ]})


def test_cookie_extraction_is_x_only_and_requires_auth_pair():
    cookies = cookies_from_storage_states((_state(),))
    assert cookies == {"auth_token": "secret-a", "ct0": "secret-b"}
    assert has_twikit_auth(cookies) is True
    assert has_twikit_auth({"auth_token": "only"}) is False


def test_explicit_proxy_is_normalized_before_system_fallback():
    assert resolve_twikit_proxy("127.0.0.1:10086") == "http://127.0.0.1:10086"


def test_adapter_passes_proxy_and_user_agent_to_twikit_client():
    created = {}
    class FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)
        def load_cookies(self, _path):
            pass
    fake_module = SimpleNamespace(Client=FakeClient)
    with patch("app.platforms.x.twikit_client.importlib.import_module", return_value=fake_module):
        TwikitReadAdapter((_state(),), proxy="127.0.0.1:10086", user_agent="ua-fixture")
    assert created["proxy"] == "http://127.0.0.1:10086"
    assert created["user_agent"] == "ua-fixture"


def test_adapter_restores_event_loop_policy_after_twikit_import():
    import asyncio

    created = {}
    class FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)
        def load_cookies(self, _path):
            pass

    fake_module = SimpleNamespace(Client=FakeClient)
    original_policy = asyncio.get_event_loop_policy()
    replacement_policy = type(original_policy)()

    def fake_import(_name):
        asyncio.set_event_loop_policy(replacement_policy)
        return fake_module

    with (
        patch("app.platforms.x.twikit_client.patch_twikit_transaction"),
        patch("app.platforms.x.twikit_client.patch_twikit_user_models"),
        patch("app.platforms.x.twikit_client.importlib.import_module", side_effect=fake_import),
    ):
        TwikitReadAdapter((_state(),))

    assert asyncio.get_event_loop_policy() is original_policy


def test_adapter_fails_closed_when_auth_is_missing():
    with pytest.raises(TwikitAuthUnavailable):
        TwikitReadAdapter((json.dumps({"cookies": []}),))


def test_timeline_uses_latest_timeline_read_method():
    class FakeClient:
        async def get_latest_timeline(self, count):
            assert count == 7
            return [SimpleNamespace(id="123", full_text="hello", user=SimpleNamespace(
                screen_name="tester", name="Tester", id="9"), created_at="now",
                reply_count=1, retweet_count=2, favorite_count=3, view_count=4)]

    adapter = object.__new__(TwikitReadAdapter)
    adapter._client = FakeClient()
    import asyncio
    rows = asyncio.run(adapter.timeline(count=7))
    assert rows[0]["id"] == "123"
    assert rows[0]["author"]["handle"] == "tester"


def test_provider_prefers_twikit_for_reads_but_browser_for_writes():
    with (
        patch("app.platforms.x.providers.agent_reach_available", return_value=False),
        patch("app.platforms.x.providers.importlib.util.find_spec", return_value=object()),
    ):
        status = x_provider_status()
    assert status["default_read"] == "twikit"
    assert status["fallback_read"] == "browser"
    assert status["write_provider"] == "browser"


def test_adapter_fails_closed_when_optional_dependency_is_missing():
    real_import = __import__("importlib").import_module
    def fake_import(name):
        if name == "twikit":
            raise ImportError("fixture")
        return real_import(name)
    with patch("app.platforms.x.twikit_client.importlib.import_module", side_effect=fake_import):
        with pytest.raises(TwikitUnavailable):
            TwikitReadAdapter((_state(),))


@pytest.mark.parametrize("value", ["", "abc", "123x"])
def test_get_tweet_rejects_non_numeric_id_without_network(value):
    adapter = object.__new__(TwikitReadAdapter)
    adapter._client = SimpleNamespace()
    with pytest.raises(ValueError):
        import asyncio
        asyncio.run(adapter.get_tweet(value))


def test_mentions_extracts_target_tweets_and_deduplicates_notifications():
    class FakeClient:
        async def get_notifications(self, kind, count):
            assert kind == "Mentions"
            tweet = SimpleNamespace(id="123", full_text="actual mention", user=None)
            return [SimpleNamespace(id="notification-1", tweet=tweet),
                    SimpleNamespace(id="notification-2", tweet=tweet),
                    SimpleNamespace(id="notification-3", tweet=None)]
    adapter = object.__new__(TwikitReadAdapter)
    adapter._client = FakeClient()
    import asyncio
    rows = asyncio.run(adapter.mentions(count=3))
    assert len(rows) == 1
    assert rows[0]["id"] == "123"
    assert rows[0]["text"] == "actual mention"
