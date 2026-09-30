"""Read-only Agent Reach adapter for X.

CreatorHub uses the locally configured Agent Reach/twitter safe wrapper only for
reads. BrowserManager remains authoritative for every write operation.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any


class AgentReachUnavailable(RuntimeError):
    pass


class AgentReachAuthMismatch(RuntimeError):
    pass


class AgentReachUnsupported(RuntimeError):
    pass


class AgentReachSchemaError(RuntimeError):
    pass


class AgentReachCommandError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "command_error")
        self.message = str(message or "Agent Reach X read failed")


_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATUS_TTL_SECONDS = 60.0


def _resolve_twitter_command() -> str:
    if os.name == "nt":
        appdata = str(os.environ.get("APPDATA") or "").strip()
        if appdata:
            safe = Path(appdata) / "npm" / "twitter.cmd"
            if safe.is_file():
                return str(safe)
    resolved = shutil.which("twitter")
    if not resolved:
        raise AgentReachUnavailable("Agent Reach 的 twitter 只读后端未安装或不在 PATH")
    return resolved


def agent_reach_available() -> bool:
    try:
        _resolve_twitter_command()
        return True
    except AgentReachUnavailable:
        return False


def _normalize_tweet(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    tweet_id = str(item.get("id") or "")
    handle = str(author.get("screenName") or author.get("username") or "")
    return {
        "id": tweet_id,
        "url": f"https://x.com/{handle or 'i/web'}/status/{tweet_id}" if tweet_id else "",
        "text": str(item.get("text") or ""),
        "author": {
            "handle": handle,
            "name": str(author.get("name") or ""),
            "id": str(author.get("id") or ""),
            "verified": bool(author.get("verified")),
            "avatar": str(author.get("profileImageUrl") or ""),
        },
        "created_at": str(item.get("createdAtISO") or item.get("createdAt") or ""),
        "metrics": {
            "reply": int(metrics.get("replies") or 0),
            "retweet": int(metrics.get("retweets") or 0),
            "like": int(metrics.get("likes") or 0),
            "view": int(metrics.get("views") or 0),
        },
    }


def _normalize_relationship(item: dict[str, Any], direction: str) -> dict[str, Any]:
    handle = str(item.get("screenName") or item.get("username") or "").strip()
    verified = bool(item.get("verified"))
    return {
        "uid": handle,
        "sec_uid": handle,
        "nickname": str(item.get("name") or handle),
        "avatar": str(item.get("profileImageUrl") or ""),
        "signature": str(item.get("bio") or ""),
        "is_mutual": False,
        "is_following": direction == "following",
        "raw_json": json.dumps({
            "handle": handle,
            "x_user_id": str(item.get("id") or ""),
            "verified": verified,
            "provider": "agent_reach",
            "followers": int(item.get("followers") or 0),
            "following": int(item.get("following") or 0),
        }, ensure_ascii=False),
    }


class AgentReachReadAdapter:
    def __init__(self, expected_handle: str, *, command: str | None = None,
                 timeout_seconds: int = 150) -> None:
        self.expected_handle = str(expected_handle or "").strip().lstrip("@")
        if not self.expected_handle:
            raise AgentReachAuthMismatch(
                "CreatorHub X 账号缺少 handle，无法确认 Agent Reach 当前认证账号一致")
        self.command = command or _resolve_twitter_command()
        self.timeout_seconds = max(5, min(180, int(timeout_seconds or 150)))

    async def _run_json(self, args: list[str]) -> dict[str, Any]:
        if os.name == "nt" and Path(self.command).suffix.lower() in {".cmd", ".bat"}:
            comspec = os.environ.get("COMSPEC") or "cmd.exe"
            command_line = subprocess.list2cmdline([self.command, *args])
            proc = await asyncio.create_subprocess_exec(
                comspec, "/d", "/s", "/c", command_line,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                self.command, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise AgentReachCommandError(
                "timeout", "Agent Reach X 读取超时") from exc

        raw = stdout.decode("utf-8-sig", errors="replace").strip()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise AgentReachSchemaError(
                f"Agent Reach X 返回非 JSON 数据: {detail or raw[:160]}") from exc

        if not isinstance(payload, dict):
            raise AgentReachSchemaError("Agent Reach X 返回结构不是对象")
        if payload.get("ok") is not True:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            code = str(error.get("code") or f"exit_{proc.returncode}")
            message = str(error.get("message") or "Agent Reach X read failed")
            raise AgentReachCommandError(code, message)
        if proc.returncode not in (0, None):
            raise AgentReachCommandError(
                f"exit_{proc.returncode}",
                stderr.decode("utf-8", errors="replace").strip()
                or "Agent Reach X command failed")
        return payload

    async def _status_user(self) -> dict[str, Any]:
        cache_key = str(Path(self.command)).casefold()
        cached = _STATUS_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < _STATUS_TTL_SECONDS:
            return cached[1]
        payload = await self._run_json(["status", "--json"])
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if not data.get("authenticated") or not user:
            raise AgentReachAuthMismatch("Agent Reach X 当前没有有效认证账号")
        _STATUS_CACHE[cache_key] = (now, user)
        return user

    async def _assert_account(self) -> dict[str, Any]:
        user = await self._status_user()
        actual = str(
            user.get("screenName") or user.get("username") or "").strip().lstrip("@")
        if not actual or actual.casefold() != self.expected_handle.casefold():
            raise AgentReachAuthMismatch(
                f"Agent Reach 当前账号 @{actual or '?'} 与 CreatorHub 账号 "
                f"@{self.expected_handle} 不一致")
        return user

    async def profile(self) -> dict[str, Any]:
        user = await self._assert_account()
        return {
            "nickname": str(user.get("name") or self.expected_handle),
            "handle": self.expected_handle,
            "follower_count": int(user.get("followers") or 0),
            "following_count": int(user.get("following") or 0),
            "aweme_count": int(user.get("tweets") or 0),
            "avatar": str(user.get("profileImageUrl") or ""),
            "verified": bool(user.get("verified")),
        }

    async def timeline(self, *, count: int = 20) -> list[dict[str, Any]]:
        await self._assert_account()
        n = max(1, min(100, int(count or 20)))
        payload = await self._run_json(
            ["feed", "-t", "following", "-n", str(n), "--json"])
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise AgentReachSchemaError("Agent Reach timeline 缺少 data 列表")
        return [_normalize_tweet(row) for row in rows if isinstance(row, dict)]

    async def search(self, query: str, *, count: int = 20,
                     product: str = "Latest") -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            raise ValueError("X 搜索关键词不能为空")
        if str(product or "Latest").strip().lower() != "latest":
            raise AgentReachUnsupported(
                "Agent Reach 当前仅接管 Latest 搜索，其他类型继续使用 Twikit/Browser")
        await self._assert_account()
        n = max(1, min(100, int(count or 20)))
        payload = await self._run_json(["search", text, "-n", str(n), "--json"])
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise AgentReachSchemaError("Agent Reach search 缺少 data 列表")
        return [_normalize_tweet(row) for row in rows if isinstance(row, dict)]

    async def user_profile(self, handle: str) -> dict[str, Any]:
        target = str(handle or "").strip().lstrip("@")
        if not target:
            raise ValueError("X user handle不能为空")
        await self._assert_account()
        payload = await self._run_json(["user", target, "--json"])
        row = payload.get("data")
        if not isinstance(row, dict):
            raise AgentReachSchemaError("Agent Reach user 缺少 data 对象")
        actual = str(
            row.get("screenName") or row.get("username") or target
        ).strip().lstrip("@")
        return {
            "handle": actual or target,
            "nickname": str(row.get("name") or actual or target),
            "id": str(row.get("id") or ""),
            "avatar": str(row.get("profileImageUrl") or ""),
            "bio": str(row.get("bio") or ""),
            "followers": int(row.get("followers") or 0),
            "following": int(row.get("following") or 0),
            "tweets": int(row.get("tweets") or 0),
            "likes": int(row.get("likes") or 0),
            "verified": bool(row.get("verified")),
            "created_at": str(row.get("createdAt") or row.get("createdAtISO") or ""),
        }

    async def user_posts(self, handle: str, *, count: int = 3) -> list[dict[str, Any]]:
        target = str(handle or "").strip().lstrip("@")
        if not target:
            raise ValueError("X user-posts handle不能为空")
        await self._assert_account()
        n = max(1, min(20, int(count or 3)))
        payload = await self._run_json(
            ["user-posts", target, "-n", str(n), "--json"])
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise AgentReachSchemaError("Agent Reach user-posts 缺少 data 列表")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or bool(row.get("isRetweet")):
                continue
            author = row.get("author") if isinstance(row.get("author"), dict) else {}
            actual = str(
                author.get("screenName") or author.get("username") or "").strip().lstrip("@")
            if actual and actual.casefold() != target.casefold():
                continue
            normalized.append(_normalize_tweet(row))
        return normalized

    async def relationships(
            self, direction: str, *, count: int = 300
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if direction not in {"following", "fan"}:
            raise ValueError("direction must be following or fan")
        profile = await self.profile()
        requested = max(1, min(2000, int(count or 300)))
        advertised_total = max(0, int(
            profile.get("following_count" if direction == "following"
                        else "follower_count") or 0))
        # Avoid asking twitter-cli for 2000 rows when X itself reports a much
        # smaller current relationship total. Its cursor loop otherwise keeps
        # paging well past the useful tail and makes ~1k syncs unnecessarily
        # slow or timeout-prone. Explicit smaller caller limits still win.
        n = min(requested, advertised_total) if advertised_total else requested
        n = max(1, n)
        command = "following" if direction == "following" else "followers"
        try:
            payload = await self._run_json(
                [command, self.expected_handle, "-n", str(n), "--json"])
        except AgentReachCommandError as exc:
            # twitter-cli 0.8.5 currently returns HTTP 404 for followers on
            # some accounts. Treat that as provider incompatibility so the
            # BrowserManager path can take over without disabling the page.
            if exc.code == "not_found":
                raise AgentReachUnsupported(
                    f"Agent Reach {command} 当前不可用: {exc.message}") from exc
            raise
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise AgentReachSchemaError(
                f"Agent Reach {command} 缺少 data 列表")
        return (
            [_normalize_relationship(row, direction)
             for row in rows if isinstance(row, dict)],
            profile,
        )
