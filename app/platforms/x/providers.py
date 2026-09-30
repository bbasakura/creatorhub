"""X backend/provider registry.

Browser automation remains authoritative for writes. Optional web clients may
accelerate reads/search, but must not silently bypass CreatorHub's shared risk
controller, account lock, or submit-boundary semantics.
"""
from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from typing import Literal

from .agent_reach import agent_reach_available


@dataclass(frozen=True)
class XProviderCapability:
    name: str
    kind: Literal["browser", "web_client", "cli"]
    available: bool
    read: bool
    write: bool
    search: bool
    timeline: bool
    relationships: bool
    dm: bool
    authoritative_for_writes: bool = False
    note: str = ""


def browser_provider_capability() -> XProviderCapability:
    return XProviderCapability(
        name="browser", kind="browser", available=True,
        read=True, write=True, search=False, timeline=True,
        relationships=True, dm=True, authoritative_for_writes=True,
        note="Persistent BrowserManager profile with shared risk gates and submit-boundary semantics.",
    )


def agent_reach_provider_capability() -> XProviderCapability:
    available = agent_reach_available()
    return XProviderCapability(
        name="agent_reach", kind="cli", available=available,
        read=available, write=False, search=available, timeline=available,
        relationships=available, dm=False, authoritative_for_writes=False,
        note=(
            "Agent Reach/twitter safe wrapper; read-only and account-matched per request."
            if available else
            "Agent Reach twitter safe wrapper is not available; continue with Twikit/Browser."
        ),
    )


def twikit_provider_capability() -> XProviderCapability:
    available = importlib.util.find_spec("twikit") is not None
    return XProviderCapability(
        name="twikit", kind="web_client", available=available,
        read=available, write=False, search=available, timeline=available,
        relationships=available, dm=False, authoritative_for_writes=False,
        note=(
            "Optional read/search/mentions accelerator only; browser remains the write backend."
            if available else
            "Optional dependency is not installed; browser read backend remains active."
        ),
    )


def x_provider_status() -> dict:
    browser = browser_provider_capability()
    agent_reach = agent_reach_provider_capability()
    twikit = twikit_provider_capability()
    providers = [browser, agent_reach, twikit]
    if agent_reach.available:
        default_read = "agent_reach"
    elif twikit.available:
        default_read = "twikit"
    else:
        default_read = "browser"
    read_chain = [
        provider.name for provider in (agent_reach, twikit, browser)
        if provider.available
    ]
    return {
        "default_read": default_read,
        "fallback_read": (
            "twikit" if default_read == "agent_reach" and twikit.available
            else "browser"
        ),
        "read_chain": read_chain,
        "write_provider": "browser",
        "providers": [asdict(provider) for provider in providers],
    }
