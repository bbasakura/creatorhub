import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.platforms.x.agent_reach import (
    AgentReachAuthMismatch,
    AgentReachReadAdapter,
    AgentReachUnsupported,
    _normalize_relationship,
    _normalize_tweet,
)


def test_agent_reach_normalizes_verified_tweet():
    row = _normalize_tweet({
        "id": "123",
        "text": "hello",
        "author": {
            "id": "9", "name": "Tester", "screenName": "tester",
            "verified": True, "profileImageUrl": "avatar",
        },
        "metrics": {"likes": 3, "retweets": 2, "replies": 1, "views": 4},
        "createdAtISO": "2026-09-29T00:00:00+00:00",
    })
    assert row["author"]["handle"] == "tester"
    assert row["author"]["verified"] is True
    assert row["metrics"] == {"reply": 1, "retweet": 2, "like": 3, "view": 4}


def test_agent_reach_relationship_persists_verified_in_raw_json():
    import json
    row = _normalize_relationship({
        "id": "9", "name": "Tester", "screenName": "tester",
        "verified": True, "profileImageUrl": "avatar", "bio": "bio",
    }, "following")
    assert row["sec_uid"] == "tester"
    assert json.loads(row["raw_json"])["verified"] is True


def test_agent_reach_refuses_wrong_creatorhub_account():
    adapter = AgentReachReadAdapter("wanted", command="twitter")
    adapter._status_user = AsyncMock(return_value={"screenName": "other"})
    with pytest.raises(AgentReachAuthMismatch):
        asyncio.run(adapter.timeline(count=1))


def test_agent_reach_profile_normalizes_current_counts():
    adapter = AgentReachReadAdapter("tester", command="twitter")
    adapter._assert_account = AsyncMock(return_value={
        "screenName": "tester", "name": "Tester",
        "followers": 571, "following": 969, "tweets": 44,
        "verified": True, "profileImageUrl": "avatar",
    })
    profile = asyncio.run(adapter.profile())
    assert profile["follower_count"] == 571
    assert profile["following_count"] == 969
    assert profile["verified"] is True


def test_agent_reach_relationship_caps_requested_count_to_current_profile_total():
    adapter = AgentReachReadAdapter("tester", command="twitter")
    adapter._assert_account = AsyncMock(return_value={
        "screenName": "tester", "followers": 570, "following": 961,
        "verified": True,
    })
    adapter._run_json = AsyncMock(return_value={"ok": True, "data": []})
    rows, profile = asyncio.run(adapter.relationships("following", count=2000))
    assert rows == []
    assert profile["following_count"] == 961
    assert profile["follower_count"] == 570
    adapter._run_json.assert_awaited_once_with(
        ["following", "tester", "-n", "961", "--json"])


def test_agent_reach_relationship_keeps_explicit_smaller_limit():
    adapter = AgentReachReadAdapter("tester", command="twitter")
    adapter._assert_account = AsyncMock(return_value={
        "screenName": "tester", "followers": 570, "following": 961})
    adapter._run_json = AsyncMock(return_value={"ok": True, "data": []})
    asyncio.run(adapter.relationships("following", count=100))
    adapter._run_json.assert_awaited_once_with(
        ["following", "tester", "-n", "100", "--json"])


def test_agent_reach_followers_not_found_becomes_fallback_signal():
    adapter = AgentReachReadAdapter("tester", command="twitter")
    adapter._assert_account = AsyncMock(return_value={
        "screenName": "tester", "followers": 1, "following": 2})
    from app.platforms.x.agent_reach import AgentReachCommandError
    adapter._run_json = AsyncMock(
        side_effect=AgentReachCommandError("not_found", "404"))
    with pytest.raises(AgentReachUnsupported):
        asyncio.run(adapter.relationships("fan", count=1))
