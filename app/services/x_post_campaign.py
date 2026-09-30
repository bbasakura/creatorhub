from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from ..settings import get_setting, set_setting

POST_CAMPAIGN_PREFIX = "x_post_campaign:"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else ""


def _key(account_id: int) -> str:
    return f"{POST_CAMPAIGN_PREFIX}{int(account_id)}"


def _defaults(account_id: int) -> dict[str, Any]:
    return {
        "version": 1,
        "account_id": int(account_id),
        "enabled": False,
        "status": "stopped",
        "target_count": 1,
        "run_published": 0,
        "total_published": 0,
        "queued_count": 0,
        "run_token": "",
        "last_task_id": 0,
        "last_text": "",
        "last_url": "",
        "last_error": "",
        "started_at": "",
        "next_due_at": "",
        "updated_at": "",
        "counted_task_ids": [],
    }


def load_post_campaign(account_id: int) -> dict[str, Any]:
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
    state["target_count"] = max(1, int(state.get("target_count") or 1))
    state["counted_task_ids"] = [
        int(value) for value in (state.get("counted_task_ids") or [])
        if str(value).isdigit()
    ][-500:]
    return state


def save_post_campaign(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["updated_at"] = _iso(_utcnow())
    state["counted_task_ids"] = list(state.get("counted_task_ids") or [])[-500:]
    set_setting(_key(int(state["account_id"])), json.dumps(state, ensure_ascii=False))
    return state


def start_post_campaign(account_id: int, *, target_count: int) -> dict[str, Any]:
    state = load_post_campaign(account_id)
    now = _utcnow()
    state.update({
        "enabled": True,
        "status": "running",
        "target_count": max(1, int(target_count or 1)),
        "run_published": 0,
        "queued_count": 0,
        "run_token": now.strftime("%Y%m%d%H%M%S"),
        "last_task_id": 0,
        "last_text": "",
        "last_url": "",
        "last_error": "",
        "started_at": _iso(now),
        "next_due_at": "",
        "counted_task_ids": [],
    })
    return save_post_campaign(state)


def stop_post_campaign(account_id: int, *, reason: str = "人工停止") -> dict[str, Any]:
    state = load_post_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "stopped",
        "last_error": str(reason or "")[:1000],
    })
    return save_post_campaign(state)


def post_campaign_due(state: dict[str, Any]) -> bool:
    if not state.get("enabled"):
        return False
    if int(state.get("run_published") or 0) >= max(
            1, int(state.get("target_count") or 1)):
        return False
    next_due = str(state.get("next_due_at") or "").strip()
    if next_due:
        try:
            due_at = datetime.fromisoformat(next_due.replace("Z", "+00:00"))
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            if _utcnow() < due_at.astimezone(timezone.utc):
                return False
        except ValueError:
            pass
    return True


def next_post_intent_id(state: dict[str, Any]) -> str:
    seq = int(state.get("queued_count") or 0) + 1
    token = str(state.get("run_token") or _utcnow().strftime("%Y%m%d%H%M%S"))
    return f"oneclick-{token}-{seq:04d}"


def mark_post_queued(account_id: int, *, task_id: int, text: str) -> dict[str, Any]:
    state = load_post_campaign(account_id)
    state["queued_count"] = int(state.get("queued_count") or 0) + 1
    state["last_task_id"] = int(task_id)
    state["last_text"] = str(text or "")
    state["last_error"] = ""
    state["status"] = "running"
    return save_post_campaign(state)


def mark_post_success(account_id: int, *, task_id: int, text: str = "",
                      result_url: str = "") -> dict[str, Any]:
    state = load_post_campaign(account_id)
    counted = {int(value) for value in state.get("counted_task_ids") or []}
    newly_counted = int(task_id) not in counted
    if newly_counted:
        counted.add(int(task_id))
        state["counted_task_ids"] = sorted(counted)[-500:]
        state["run_published"] = int(state.get("run_published") or 0) + 1
        state["total_published"] = int(state.get("total_published") or 0) + 1
    state["last_task_id"] = int(task_id)
    if text:
        state["last_text"] = str(text)
    if result_url:
        state["last_url"] = str(result_url)
    state["last_error"] = ""
    if int(state.get("run_published") or 0) >= max(1, int(state.get("target_count") or 1)):
        state["enabled"] = False
        state["status"] = "completed"
        state["next_due_at"] = ""
    else:
        state["status"] = "running"
        if newly_counted:
            state["next_due_at"] = _iso(
                _utcnow() + timedelta(seconds=random.randint(300, 600)))
    return save_post_campaign(state)


def mark_post_uncertain(account_id: int, *, task_id: int, reason: str) -> dict[str, Any]:
    state = load_post_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "paused_uncertain",
        "last_task_id": int(task_id),
        "last_error": str(reason or "发布结果不确定，已停止一键发帖")[:1000],
    })
    return save_post_campaign(state)


def mark_post_failed(account_id: int, *, task_id: int, reason: str) -> dict[str, Any]:
    state = load_post_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "paused_error",
        "last_task_id": int(task_id),
        "last_error": str(reason or "发布失败，已停止一键发帖")[:1000],
    })
    return save_post_campaign(state)


def mark_post_login_required(account_id: int, *, reason: str = "") -> dict[str, Any]:
    state = load_post_campaign(account_id)
    state.update({
        "enabled": False,
        "status": "login_required",
        "last_error": str(reason or "X登录态失效，请在面板手动登录后重试")[:1000],
    })
    return save_post_campaign(state)
