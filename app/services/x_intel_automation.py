"""Persistent configuration/state helpers for automated X intelligence."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import select

from ..db import get_session
from ..models import (
    DouyinAccount, XIntelAlert, XIntelDailyBrief, XIntelScan,
)
from ..settings import get_setting, set_setting


DEFAULT_X_INTEL_AUTOMATION = {
    "enabled": False,
    "interval_hours": 3,
    "posts_per_account": 5,
    "max_accounts": 30,
    "daily_brief_enabled": True,
    "daily_brief_hour": 20,
    "notify_explosions": True,
    "notify_daily_brief": True,
    "auto_opportunities_enabled": False,
    "auto_draft_count": 3,
    "explosion_min_views_per_hour": 300.0,
    "explosion_min_view_delta": 800,
    "explosion_min_efficiency": 0.5,
    "explosion_min_engagement_rate": 0.02,
}


def _key(account_id: int) -> str:
    return f"x_intel_automation:{int(account_id)}"


def normalize_x_intel_automation(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_X_INTEL_AUTOMATION)
    if isinstance(raw, dict):
        cfg.update(raw)
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["interval_hours"] = max(1, min(24, int(cfg.get("interval_hours") or 3)))
    cfg["posts_per_account"] = max(1, min(10, int(cfg.get("posts_per_account") or 5)))
    cfg["max_accounts"] = max(1, min(50, int(cfg.get("max_accounts") or 30)))
    cfg["daily_brief_enabled"] = bool(cfg.get("daily_brief_enabled", True))
    cfg["daily_brief_hour"] = max(0, min(23, int(cfg.get("daily_brief_hour") or 20)))
    cfg["notify_explosions"] = bool(cfg.get("notify_explosions", True))
    cfg["notify_daily_brief"] = bool(cfg.get("notify_daily_brief", True))
    cfg["auto_opportunities_enabled"] = bool(
        cfg.get("auto_opportunities_enabled", False))
    cfg["auto_draft_count"] = max(
        1, min(6, int(cfg.get("auto_draft_count") or 3)))
    cfg["explosion_min_views_per_hour"] = max(
        1.0, min(10000000.0, float(cfg.get("explosion_min_views_per_hour") or 300.0)))
    cfg["explosion_min_view_delta"] = max(
        1, min(100000000, int(cfg.get("explosion_min_view_delta") or 800)))
    cfg["explosion_min_efficiency"] = max(
        0.0, min(100000.0, float(cfg.get("explosion_min_efficiency") or 0.5)))
    cfg["explosion_min_engagement_rate"] = max(
        0.0, min(1.0, float(cfg.get("explosion_min_engagement_rate") or 0.02)))
    return cfg


def load_x_intel_automation(account_id: int) -> dict[str, Any]:
    raw = get_setting(_key(account_id), "")
    if not raw:
        return normalize_x_intel_automation(None)
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}
    return normalize_x_intel_automation(parsed)


def save_x_intel_automation(account_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    cfg = normalize_x_intel_automation(raw)
    set_setting(_key(account_id), json.dumps(cfg, ensure_ascii=False, separators=(",", ":")))
    return cfg


def scan_schedule(account_id: int, cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.utcnow()
    with get_session() as session:
        latest = session.exec(select(XIntelScan).where(
            XIntelScan.account_id == int(account_id)
        ).order_by(XIntelScan.id.desc()).limit(1)).first()
        running = session.exec(select(XIntelScan).where(
            XIntelScan.account_id == int(account_id),
            XIntelScan.status == "running",
        ).order_by(XIntelScan.id.desc()).limit(1)).first()
    interval = timedelta(hours=int(cfg.get("interval_hours") or 3))
    last_at = None
    if latest:
        last_at = latest.finished_at or latest.started_at
    next_at = (last_at + interval) if last_at else current
    return {
        "due": bool(cfg.get("enabled")) and not running and current >= next_at,
        "running": bool(running),
        "last_scan_id": latest.id if latest else None,
        "last_scan_at": (last_at.isoformat() + "Z") if last_at else None,
        "next_scan_at": (next_at.isoformat() + "Z") if next_at else None,
    }


def account_local_now(account: DouyinAccount, now_utc: datetime | None = None) -> datetime:
    current = now_utc or datetime.utcnow()
    tz_name = str(account.timezone_id or "Asia/Shanghai")
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = ZoneInfo("Asia/Shanghai")
    if current.tzinfo is None:
        from datetime import timezone
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(zone)


def daily_brief_due(
        account: DouyinAccount, cfg: dict[str, Any],
        now_utc: datetime | None = None) -> dict[str, Any]:
    local_now = account_local_now(account, now_utc)
    local_date = local_now.strftime("%Y-%m-%d")
    with get_session() as session:
        existing = session.exec(select(XIntelDailyBrief).where(
            XIntelDailyBrief.account_id == int(account.id),
            XIntelDailyBrief.local_date == local_date,
        ).order_by(XIntelDailyBrief.id.desc()).limit(1)).first()
    return {
        "due": (
            bool(cfg.get("enabled"))
            and bool(cfg.get("daily_brief_enabled"))
            and local_now.hour >= int(cfg.get("daily_brief_hour") or 20)
            and existing is None
        ),
        "local_date": local_date,
        "local_time": local_now.isoformat(),
        "existing_brief_id": existing.id if existing else None,
    }


def persist_explosion_alerts(
        account_id: int, scan_id: int, candidates: list[dict[str, Any]]) -> list[XIntelAlert]:
    created: list[XIntelAlert] = []
    with get_session() as session:
        existing_rows = session.exec(select(XIntelAlert).where(
            XIntelAlert.account_id == int(account_id),
            XIntelAlert.alert_type == "explosion",
        )).all()
        known = {str(row.tweet_id or "") for row in existing_rows}
        for item in candidates:
            tweet_id = str(item.get("tweet_id") or "")
            if not tweet_id or tweet_id in known:
                continue
            row = XIntelAlert(
                account_id=int(account_id),
                scan_id=int(scan_id),
                tweet_id=tweet_id,
                tweet_url=str(item.get("tweet_url") or ""),
                author_handle=str(item.get("author_handle") or ""),
                author_name=str(item.get("author_name") or ""),
                alert_type="explosion",
                level=str(item.get("level") or "rising"),
                window_hours=int(item.get("window_hours") or 0),
                view_count=int(item.get("view_count") or 0),
                view_delta=int(item.get("view_delta") or 0),
                views_per_hour=float(item.get("views_per_hour") or 0),
                exposure_efficiency=float(item.get("exposure_efficiency") or 0),
                engagement_rate=float(item.get("engagement_rate") or 0),
                signal_score=float(item.get("signal_score") or 0),
                reason=str(item.get("reason") or "")[:1000],
            )
            session.add(row)
            session.flush()
            created.append(row)
            known.add(tweet_id)
        session.commit()
        for row in created:
            session.refresh(row)
    return created


def mark_alerts_notified(alert_ids: list[int], now: datetime | None = None) -> None:
    if not alert_ids:
        return
    stamp = now or datetime.utcnow()
    with get_session() as session:
        rows = session.exec(select(XIntelAlert).where(
            XIntelAlert.id.in_(alert_ids)
        )).all()
        for row in rows:
            row.notified_at = stamp
            session.add(row)
        session.commit()


def create_daily_brief(
        account_id: int, local_date: str, scan_id: int | None,
        summary: dict[str, Any], source: str, alert_count: int) -> XIntelDailyBrief:
    with get_session() as session:
        existing = session.exec(select(XIntelDailyBrief).where(
            XIntelDailyBrief.account_id == int(account_id),
            XIntelDailyBrief.local_date == str(local_date),
        ).order_by(XIntelDailyBrief.id.desc()).limit(1)).first()
        if existing:
            return existing
        row = XIntelDailyBrief(
            account_id=int(account_id),
            local_date=str(local_date),
            scan_id=int(scan_id) if scan_id else None,
            summary_json=json.dumps(summary or {}, ensure_ascii=False, separators=(",", ":")),
            summary_source=str(source or ""),
            alert_count=max(0, int(alert_count or 0)),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def mark_brief_notified(brief_id: int, now: datetime | None = None) -> None:
    with get_session() as session:
        row = session.get(XIntelDailyBrief, int(brief_id))
        if not row:
            return
        row.notified_at = now or datetime.utcnow()
        session.add(row)
        session.commit()


def alert_dict(row: XIntelAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "scan_id": row.scan_id,
        "tweet_id": row.tweet_id,
        "tweet_url": row.tweet_url,
        "author_handle": row.author_handle,
        "author_name": row.author_name,
        "alert_type": row.alert_type,
        "level": row.level,
        "window_hours": row.window_hours,
        "view_count": row.view_count,
        "view_delta": row.view_delta,
        "views_per_hour": row.views_per_hour,
        "exposure_efficiency": row.exposure_efficiency,
        "engagement_rate": row.engagement_rate,
        "signal_score": row.signal_score,
        "reason": row.reason,
        "notified_at": (row.notified_at.isoformat() + "Z") if row.notified_at else None,
        "created_at": (row.created_at.isoformat() + "Z") if row.created_at else None,
    }


def brief_dict(row: XIntelDailyBrief) -> dict[str, Any]:
    try:
        summary = json.loads(row.summary_json or "{}")
        if not isinstance(summary, dict):
            summary = {}
    except Exception:
        summary = {}
    return {
        "id": row.id,
        "account_id": row.account_id,
        "local_date": row.local_date,
        "scan_id": row.scan_id,
        "summary": summary,
        "summary_source": row.summary_source,
        "alert_count": row.alert_count,
        "notified_at": (row.notified_at.isoformat() + "Z") if row.notified_at else None,
        "generated_at": (row.generated_at.isoformat() + "Z") if row.generated_at else None,
    }
