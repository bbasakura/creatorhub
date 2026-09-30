from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api import x as x_api
from app.platforms.x.providers import x_provider_status
from app.services.runtime_context import bind_runtime, clear_runtime, get_runtime


def teardown_function(_function):
    clear_runtime()


def test_runtime_context_decouples_x_router_from_main_globals():
    browser = object()
    engine = object()
    bind_runtime(browser=browser, engine=engine)
    assert get_runtime().browser is browser
    assert get_runtime().engine is engine
    assert x_api._runtime() == (browser, engine)


def test_x_runtime_requires_bound_context():
    clear_runtime()
    with pytest.raises(HTTPException) as exc:
        x_api._runtime()
    assert exc.value.status_code == 503


def test_provider_registry_keeps_browser_authoritative_for_writes():
    with (
        patch("app.platforms.x.providers.agent_reach_available", return_value=False),
        patch("app.platforms.x.providers.importlib.util.find_spec", return_value=None),
    ):
        status = x_provider_status()
    assert status["default_read"] == "browser"
    assert status["write_provider"] == "browser"
    browser = next(p for p in status["providers"] if p["name"] == "browser")
    reach = next(p for p in status["providers"] if p["name"] == "agent_reach")
    twikit = next(p for p in status["providers"] if p["name"] == "twikit")
    assert browser["available"] is True
    assert browser["authoritative_for_writes"] is True
    assert reach["available"] is False
    assert reach["write"] is False
    assert twikit["available"] is False
    assert twikit["write"] is False


def test_provider_registry_prefers_agent_reach_for_reads():
    with (
        patch("app.platforms.x.providers.agent_reach_available", return_value=True),
        patch("app.platforms.x.providers.importlib.util.find_spec", return_value=object()),
    ):
        status = x_provider_status()
    assert status["default_read"] == "agent_reach"
    assert status["read_chain"] == ["agent_reach", "twikit", "browser"]
    assert status["write_provider"] == "browser"
