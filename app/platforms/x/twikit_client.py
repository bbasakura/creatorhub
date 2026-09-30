"""Optional twikit read adapter for X.

This module is deliberately read-only.  CreatorHub's BrowserManager remains the
only write backend so submit-boundary, risk-control, and account-lock semantics
cannot be bypassed by an optional reverse-engineered client.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .twikit_compat import patch_twikit_transaction, patch_twikit_user_models


class TwikitUnavailable(RuntimeError):
    pass


class TwikitAuthUnavailable(RuntimeError):
    pass


def _normalize_proxy_url(value: str) -> str:
    proxy = str(value or "").strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        proxy = "http://" + proxy
    return proxy


def _windows_system_proxy() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            raw = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
        if not enabled or not raw:
            return ""
        if ";" in raw or "=" in raw:
            mapping = {}
            for part in raw.split(";"):
                if "=" in part:
                    name, value = part.split("=", 1)
                    mapping[name.strip().lower()] = value.strip()
            raw = mapping.get("https") or mapping.get("http") or mapping.get("socks") or ""
        return _normalize_proxy_url(raw)
    except Exception:
        return ""


def resolve_twikit_proxy(explicit_proxy: str = "") -> str:
    explicit = _normalize_proxy_url(explicit_proxy)
    if explicit:
        return explicit
    system_proxy = _windows_system_proxy()
    if system_proxy:
        return system_proxy
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = _normalize_proxy_url(os.environ.get(name, ""))
        if value:
            return value
    return ""


def cookies_from_storage_states(states: Iterable[str]) -> dict[str, str]:
    """Extract only x.com cookies from one or more Playwright storage states."""
    cookies: dict[str, str] = {}
    for raw in states or ():
        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for item in parsed.get("cookies") or []:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").lstrip(".").lower()
            if domain != "x.com" and not domain.endswith(".x.com"):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "")
            if name and value:
                cookies[name] = value
    return cookies


def has_twikit_auth(cookies: dict[str, str]) -> bool:
    return bool(cookies.get("auth_token") and cookies.get("ct0"))


def _normalize_tweet(tweet: Any) -> dict:
    user = getattr(tweet, "user", None)
    tweet_id = str(
        getattr(tweet, "id", "") or getattr(tweet, "id_str", "") or "")
    handle = str(getattr(user, "screen_name", "") or "")
    created = getattr(tweet, "created_at", None)
    return {
        "id": tweet_id,
        "url": f"https://x.com/{handle or 'i/web'}/status/{tweet_id}" if tweet_id else "",
        "text": str(getattr(tweet, "full_text", "") or getattr(tweet, "text", "") or ""),
        "author": {
            "handle": handle,
            "name": str(getattr(user, "name", "") or ""),
            "id": str(getattr(user, "id", "") or ""),
        },
        "created_at": str(created or ""),
        "metrics": {
            "reply": int(getattr(tweet, "reply_count", 0) or 0),
            "retweet": int(getattr(tweet, "retweet_count", 0) or 0),
            "like": int(getattr(tweet, "favorite_count", 0) or 0),
            "view": int(getattr(tweet, "view_count", 0) or 0),
        },
    }


class TwikitReadAdapter:
    def __init__(self, storage_states: Iterable[str], *, language: str = "zh-CN",
                 proxy: str = "", user_agent: str = "") -> None:
        cookies = cookies_from_storage_states(storage_states)
        if not has_twikit_auth(cookies):
            raise TwikitAuthUnavailable("X storage_state 缺少 auth_token/ct0")
        previous_policy = asyncio.get_event_loop_policy()
        try:
            try:
                module = importlib.import_module("twikit")
            except ImportError as exc:
                raise TwikitUnavailable(
                    "twikit 未安装；当前继续使用 BrowserManager 读取") from exc
            patch_twikit_transaction(module)
            patch_twikit_user_models(module)
            network_proxy = resolve_twikit_proxy(proxy)
            self._client = module.Client(
                language=language,
                proxy=network_proxy or None,
                user_agent=str(user_agent or "").strip() or None,
            )
        finally:
            # twikit currently switches Windows' global policy to Selector on
            # import. Patchright/Playwright requires subprocess support from
            # Proactor, so an optional read backend must not leak that process-
            # global side effect into CreatorHub's browser write backend.
            if asyncio.get_event_loop_policy() is not previous_policy:
                asyncio.set_event_loop_policy(previous_policy)
        self._load_cookies(cookies)

    def _load_cookies(self, cookies: dict[str, str]) -> None:
        # twikit 的公开稳定入口是 load_cookies(file)。临时文件仅存在于本机，
        # load 完成即删除，日志/异常从不回显 Cookie 内容。
        fd, path = tempfile.mkstemp(prefix="creatorhub-x-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(cookies, handle, ensure_ascii=False)
            self._client.load_cookies(path)
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    async def search(self, query: str, *, product: str = "Latest", count: int = 20) -> list[dict]:
        text = str(query or "").strip()
        if not text:
            raise ValueError("X 搜索关键词不能为空")
        result = await self._client.search_tweet(text, product, max(1, min(100, int(count))))
        return [_normalize_tweet(item) for item in list(result or [])]

    async def timeline(self, *, count: int = 20) -> list[dict]:
        result = await self._client.get_latest_timeline(max(1, min(100, int(count))))
        return [_normalize_tweet(item) for item in list(result or [])]

    async def mentions(self, *, count: int = 20) -> list[dict]:
        result = await self._client.get_notifications("Mentions", max(1, min(100, int(count))))
        # Twikit returns Notification objects, not Tweet objects. Notifications
        # without a target tweet must not become empty/fabricated post records.
        tweets = {}
        for notification in result or []:
            tweet = getattr(notification, "tweet", None)
            if tweet is not None:
                row = _normalize_tweet(tweet)
                if row["id"]:
                    tweets[row["id"]] = row
        return list(tweets.values())

    async def get_tweet(self, tweet_id: str) -> dict:
        value = str(tweet_id or "").strip()
        if not value.isdigit():
            raise ValueError("X tweet_id 格式无效")
        tweet = await self._client.get_tweet_by_id(value)
        return _normalize_tweet(tweet)
