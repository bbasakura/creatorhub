"""Account relationship operations for X (Twitter).

Follow/unfollow actions reuse CreatorHub's visible persistent browser profile.
The caller is responsible for applying the shared SOCIAL risk gate and account
operation lock before invoking these functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from ...browser.identity import Identity
from ...browser.manager import BrowserManager
from .risk_probe import detect_x_write_risk

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_RESERVED_PATHS = {
    "compose", "explore", "home", "i", "login", "messages", "notifications",
    "search", "settings", "signup",
}


@dataclass(frozen=True)
class XRelationshipOutcome:
    status: Literal["success", "failed", "uncertain"]
    action: Literal["follow", "unfollow"]
    handle: str
    changed: bool = False
    state: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "success"


def normalize_x_handle(value: str) -> tuple[str, str]:
    """Normalize @handle, handle, or an X profile URL."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("X 用户名不能为空")

    handle = raw.lstrip("@")
    if "://" in raw:
        try:
            parsed = urlparse(raw)
        except Exception as exc:
            raise ValueError("X 用户链接格式无效") from exc
        if (parsed.hostname or "").lower() not in {
            "x.com", "www.x.com", "twitter.com", "www.twitter.com",
        }:
            raise ValueError("X 用户链接域名须为 x.com 或 twitter.com")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1:
            raise ValueError("请提供 X 用户主页链接，而不是推文或其他页面链接")
        handle = parts[0]

    if not _HANDLE_RE.fullmatch(handle) or handle.casefold() in _RESERVED_PATHS:
        raise ValueError("X 用户名格式无效")
    return handle, f"https://x.com/{handle}"


async def _page_logged_out(page: Any) -> bool:
    url = str(getattr(page, "url", "") or "").lower()
    if "/i/flow/login" in url or "/login" in url:
        return True
    try:
        login = page.locator('a[href="/login"], [data-testid="loginButton"]').first
        return bool(await login.count() and await login.is_visible())
    except Exception:
        return False


async def _visible_named_button(page: Any, pattern: str):
    try:
        button = page.get_by_role("button", name=re.compile(pattern, re.I)).first
        if await button.count() and await button.is_visible():
            return button
    except Exception:
        pass
    return None


async def _relationship_state(page: Any) -> tuple[str, Any]:
    following = await _visible_named_button(
        page, r"^(Following|正在关注)(?:\s|@|$)")
    if following is not None:
        return "following", following

    pending = await _visible_named_button(
        page, r"^(Pending|待处理|已请求)(?:\s|@|$)")
    if pending is not None:
        return "pending", pending

    follow = await _visible_named_button(
        page, r"^(Follow|关注)(?:\s|@|$)")
    if follow is not None:
        return "not_following", follow

    return "unknown", None


async def _wait_for_state(page: Any, expected: set[str], timeout_ms: int = 7000) -> str:
    loops = max(1, timeout_ms // 250)
    for _ in range(loops):
        state, _ = await _relationship_state(page)
        if state in expected:
            return state
        await page.wait_for_timeout(250)
    state, _ = await _relationship_state(page)
    return state


async def set_x_following(
        mgr: BrowserManager,
        identity: Identity,
        target: str,
        should_follow: bool,
) -> XRelationshipOutcome:
    """Follow/unfollow one X account and verify the resulting UI state."""
    action: Literal["follow", "unfollow"] = "follow" if should_follow else "unfollow"
    try:
        handle, profile_url = normalize_x_handle(target)
    except ValueError as exc:
        return XRelationshipOutcome("failed", action, "", error=str(exc))

    clicked = False
    try:
        async with mgr.visible_page(identity, url=profile_url) as page:
            if await _page_logged_out(page):
                return XRelationshipOutcome(
                    "failed", action, handle,
                    error="logged_out:X 登录态已失效，请重新登录",
                )
            await page.wait_for_timeout(700)
            risk_marker = await detect_x_write_risk(page)
            if risk_marker:
                return XRelationshipOutcome(
                    "failed", action, handle,
                    error=f"risk_blocked:X {action} 前检测到平台风控/验证提示: {risk_marker}",
                )
            state, button = await _relationship_state(page)

            if should_follow and state in {"following", "pending"}:
                return XRelationshipOutcome(
                    "success", action, handle, changed=False, state=state)
            if not should_follow and state == "not_following":
                return XRelationshipOutcome(
                    "success", action, handle, changed=False, state=state)
            if state == "unknown" or button is None:
                return XRelationshipOutcome(
                    "failed", action, handle,
                    error="未找到该 X 用户的关注状态按钮；可能是自己的账号、页面异常或 X 已改版",
                )

            await button.click(timeout=8000)
            clicked = True

            if should_follow:
                final_state = await _wait_for_state(page, {"following", "pending"})
                if final_state in {"following", "pending"}:
                    return XRelationshipOutcome(
                        "success", action, handle, changed=True, state=final_state)
                return XRelationshipOutcome(
                    "uncertain", action, handle, changed=True, state=final_state,
                    error="已点击关注，但未能确认最终关注状态，请先到 X 核对",
                )

            confirm = page.locator('[data-testid="confirmationSheetConfirm"]').first
            try:
                if await confirm.count() and await confirm.is_visible():
                    await confirm.click(timeout=8000)
                else:
                    named = await _visible_named_button(
                        page, r"^(Unfollow|取消关注)(?:\s|@|$)")
                    if named is not None:
                        await named.click(timeout=8000)
            except Exception as exc:
                return XRelationshipOutcome(
                    "uncertain", action, handle, changed=True,
                    error=f"已触发取关但确认步骤状态不明: {exc!r}",
                )

            final_state = await _wait_for_state(page, {"not_following"})
            if final_state == "not_following":
                return XRelationshipOutcome(
                    "success", action, handle, changed=True, state=final_state)
            return XRelationshipOutcome(
                "uncertain", action, handle, changed=True, state=final_state,
                error="已执行取关，但未能确认最终状态，请先到 X 核对",
            )
    except Exception as exc:
        status: Literal["failed", "uncertain"] = "uncertain" if clicked else "failed"
        return XRelationshipOutcome(
            status, action, handle, changed=clicked,
            error=f"X {action} 异常: {exc!r}",
        )
