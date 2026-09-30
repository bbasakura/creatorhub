from datetime import datetime, timedelta, timezone

from app.services.x_growth_campaign import (
    growth_due,
    growth_intent_match,
    growth_task_metadata,
    next_growth_source,
    parse_growth_task_metadata,
)


def test_growth_source_alternates_keyword_and_for_you():
    state = {"next_channel": "keyword", "keyword_index": 0}
    assert next_growth_source(state) == ("keyword", "#蓝V互关")
    assert next_growth_source(state) == ("for_you", "为你推荐")
    assert next_growth_source(state) == ("keyword", "浇朋友")


def test_growth_intent_has_strict_keyword_and_broader_for_you_modes():
    assert growth_intent_match("蓝V互关，有关必回")
    assert not growth_intent_match("AI agent build log")
    assert growth_intent_match("AI agent build log", broad=True)


def test_growth_due_honors_cooldown_and_next_scan():
    now = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    state = {"enabled": True, "paused_until": "", "next_scan_at": ""}
    assert growth_due(state, now=now)
    state["paused_until"] = (now + timedelta(minutes=15)).isoformat()
    assert not growth_due(state, now=now)
    state["paused_until"] = ""
    state["next_scan_at"] = (now + timedelta(seconds=60)).isoformat()
    assert not growth_due(state, now=now)
    state.update({"next_scan_at": "", "target_count": 3, "run_followed": 3})
    assert not growth_due(state, now=now)


def test_growth_task_metadata_marks_verified_gate():
    raw = growth_task_metadata(source="关键词:#蓝V互关", tweet_url="https://x.com/a/status/1")
    payload = parse_growth_task_metadata(raw)
    assert payload["campaign"] == "jiaoyou"
    assert payload["require_verified"] is True
    assert payload["source"] == "关键词:#蓝V互关"
