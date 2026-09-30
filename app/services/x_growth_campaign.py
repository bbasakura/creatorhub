from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..settings import get_setting, set_setting

GROWTH_CAMPAIGN_PREFIX = "x_growth_campaign:"
GROWTH_KEYWORDS = ("#蓝V互关", "浇朋友", "有关必回", "蓝朋友")
_MUTUAL_MARKERS = (
    "互关", "互粉", "回关", "有关必回", "关注必回", "必回关",
    "浇朋友", "蓝朋友", "蓝v互关", "蓝v互助", "诚信互暖",
)
_FOR_YOU_MARKERS = _MUTUAL_MARKERS + (
    "web3", "crypto", "ai", "人工智能", "创作者", "creator", "build in public",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else ""


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _key(account_id: int) -> str:
    return f"{GROWTH_CAMPAIGN_PREFIX}{int(account_id)}"


def _defaults(account_id: int) -> dict[str, Any]:
    return {
        "version": 1,
        "account_id": int(account_id),
        "enabled": False,
        "status": "stopped",
        "interval_seconds": 60,
        "cooldown_seconds": 900,
        "target_count": 100,
        "next_channel": "keyword",
        "keyword_index": 0,
        "next_scan_at": "",
        "paused_until": "",
        "started_at": "",
        "updated_at": "",
        "last_handle": "",
        "last_nickname": "",
        "last_source": "",
        "last_error": "",
        "total_queued": 0,
        "total_followed": 0,
        "run_followed": 0,
        "skipped_count": 0,
        "seen_handles": [],
    }


def load_growth_campaign(account_id: int) -> dict[str, Any]:
    state = _defaults(account_id)
    raw = get_setting(_key(account_id), "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                state.update(parsed)
        except Exception:
            pass
    state["account_id"] = int(account_id)
    state["interval_seconds"] = max(60, int(state.get("interval_seconds") or 60))
    state["cooldown_seconds"] = max(900, int(state.get("cooldown_seconds") or 900))
    state["target_count"] = max(1, int(state.get("target_count") or 100))
    state["seen_handles"] = list(state.get("seen_handles") or [])[-500:]
    return state


def save_growth_campaign(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["updated_at"] = _iso(_utcnow())
    state["seen_handles"] = list(state.get("seen_handles") or [])[-500:]
    set_setting(_key(int(state["account_id"])), json.dumps(state, ensure_ascii=False))
    return state


def start_growth_campaign(account_id: int, *, interval_seconds: int = 60,
                          cooldown_seconds: int = 900,
                          target_count: int = 100) -> dict[str, Any]:
    state = load_growth_campaign(account_id)
    now = _utcnow()
    state.update({
        "enabled": True,
        "status": "running",
        "interval_seconds": max(60, int(interval_seconds or 60)),
        "cooldown_seconds": max(900, int(cooldown_seconds or 900)),
        "target_count": max(1, int(target_count or 100)),
        "next_scan_at": _iso(now),
        "paused_until": "",
        "started_at": _iso(now),
        "last_error": "",
        "run_followed": 0,
    })
    return save_growth_campaign(state)


def stop_growth_campaign(account_id: int, *, reason: str = "人工停止") -> dict[str, Any]:
    state = load_growth_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "stopped",
        "paused_until": "",
        "last_error": str(reason or "")[:1000],
    })
    return save_growth_campaign(state)


def growth_due(state: dict[str, Any], *, now: datetime | None = None) -> bool:
    if not state.get("enabled"):
        return False
    if int(state.get("run_followed") or 0) >= max(1, int(state.get("target_count") or 100)):
        return False
    current = now or _utcnow()
    paused_until = _parse_iso(str(state.get("paused_until") or ""))
    if paused_until and current < paused_until:
        return False
    next_scan = _parse_iso(str(state.get("next_scan_at") or ""))
    return not next_scan or current >= next_scan


def next_growth_source(state: dict[str, Any]) -> tuple[str, str]:
    """Alternate keyword and For You channels; rotate keyword after each For You turn."""
    channel = str(state.get("next_channel") or "keyword")
    index = int(state.get("keyword_index") or 0) % len(GROWTH_KEYWORDS)
    if channel == "for_you":
        state["next_channel"] = "keyword"
        state["keyword_index"] = (index + 1) % len(GROWTH_KEYWORDS)
        return "for_you", "为你推荐"
    state["next_channel"] = "for_you"
    return "keyword", GROWTH_KEYWORDS[index]


def growth_intent_match(text: str, *, broad: bool = False) -> bool:
    haystack = str(text or "").casefold()
    markers = _FOR_YOU_MARKERS if broad else _MUTUAL_MARKERS
    return any(marker.casefold() in haystack for marker in markers)


def growth_seen(state: dict[str, Any], handle: str) -> bool:
    key = str(handle or "").strip().lstrip("@").casefold()
    return bool(key and key in {str(v).casefold() for v in state.get("seen_handles") or []})


def mark_growth_skipped(state: dict[str, Any], handle: str = "") -> dict[str, Any]:
    handle_key = str(handle or "").strip().lstrip("@").casefold()
    seen = list(state.get("seen_handles") or [])
    if handle_key and handle_key not in {str(v).casefold() for v in seen}:
        seen.append(handle_key)
    state["seen_handles"] = seen[-500:]
    state["skipped_count"] = int(state.get("skipped_count") or 0) + 1
    return state


def defer_growth_scan(state: dict[str, Any], *, error: str = "",
                      seconds: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    current = now or _utcnow()
    delay = max(60, int(seconds or state.get("interval_seconds") or 60))
    state["next_scan_at"] = _iso(current + timedelta(seconds=delay))
    if error:
        state["last_error"] = str(error)[:1000]
    return state


def mark_growth_queued(state: dict[str, Any], *, handle: str, nickname: str,
                       source: str, now: datetime | None = None) -> dict[str, Any]:
    current = now or _utcnow()
    mark_growth_skipped(state, handle)
    state["skipped_count"] = max(0, int(state.get("skipped_count") or 0) - 1)
    state["total_queued"] = int(state.get("total_queued") or 0) + 1
    state["last_handle"] = str(handle or "").lstrip("@")
    state["last_nickname"] = str(nickname or "")
    state["last_source"] = str(source or "")
    state["last_error"] = ""
    state["status"] = "running"
    state["next_scan_at"] = _iso(
        current + timedelta(seconds=max(60, int(state.get("interval_seconds") or 60))))
    return state


def mark_growth_success(account_id: int, *, handle: str, nickname: str = "",
                        source: str = "") -> dict[str, Any]:
    state = load_growth_campaign(account_id)
    state["total_followed"] = int(state.get("total_followed") or 0) + 1
    state["run_followed"] = int(state.get("run_followed") or 0) + 1
    state["last_handle"] = str(handle or "").lstrip("@")
    state["last_nickname"] = str(nickname or "")
    state["last_source"] = str(source or state.get("last_source") or "")
    state["last_error"] = ""
    if int(state.get("run_followed") or 0) >= max(1, int(state.get("target_count") or 100)):
        state["enabled"] = False
        state["status"] = "completed"
        state["paused_until"] = ""
        state["next_scan_at"] = ""
    return save_growth_campaign(state)


def mark_growth_cooldown(account_id: int, *, reason: str,
                         external_until: datetime | None = None) -> dict[str, Any]:
    state = load_growth_campaign(account_id)
    now = _utcnow()
    until = now + timedelta(seconds=max(900, int(state.get("cooldown_seconds") or 900)))
    if external_until:
        external = external_until
        if external.tzinfo is None:
            external = external.replace(tzinfo=timezone.utc)
        if external > until:
            until = external
    state.update({
        "enabled": True,
        "status": "cooldown",
        "paused_until": _iso(until),
        "next_scan_at": _iso(until),
        "last_error": str(reason or "X 限流，自动冷却")[:1000],
    })
    return save_growth_campaign(state)


def mark_growth_login_required(account_id: int, *, reason: str = "") -> dict[str, Any]:
    state = load_growth_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "login_required",
        "last_error": str(reason or "X登录态失效，请在面板手动登录后重试")[:1000],
    })
    return save_growth_campaign(state)


def mark_growth_uncertain(account_id: int, *, reason: str) -> dict[str, Any]:
    state = load_growth_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "paused_uncertain",
        "last_error": str(reason or "关注结果不确定，已停止自动浇友")[:1000],
    })
    return save_growth_campaign(state)


def growth_task_metadata(*, source: str, tweet_url: str = "", intent_text: str = "") -> str:
    return json.dumps({
        "campaign": "jiaoyou",
        "source": str(source or ""),
        "tweet_url": str(tweet_url or ""),
        "intent_text": str(intent_text or "")[:500],
        "require_verified": True,
    }, ensure_ascii=False)


def parse_growth_task_metadata(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or ""))
        return payload if isinstance(payload, dict) and payload.get("campaign") == "jiaoyou" else {}
    except Exception:
        return {}
