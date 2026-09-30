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

    follow_back = await _visible_named_button(
        page, r"^(Follow back|回关)(?:\s|@|$)")
    if follow_back is not None:
        return "not_following", follow_back

    subscribe = await _visible_named_button(
        page, r"^(Subscribe|订阅)(?:\s|@|$)")
    if subscribe is not None:
        return "not_following", subscribe

    return "unknown", None


async def _profile_verified(page: Any) -> bool:
    try:
        node = page.locator(
            '[data-testid="UserName"] [data-testid="icon-verified"], '
            '[data-testid="primaryColumn"] [data-testid="icon-verified"], '
            'svg[aria-label*="Verified"], svg[aria-label*="认证"]'
        ).first
        return bool(await node.count() and await node.is_visible())
    except Exception:
        return False


async def inspect_x_growth_profile(
        mgr: BrowserManager, identity: Identity, target: str) -> dict[str, Any]:
    handle, profile_url = normalize_x_handle(target)
    async with mgr.visible_page(identity, url=profile_url) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        await page.wait_for_timeout(700)
        risk_marker = await detect_x_write_risk(page)
        state, _button = await _relationship_state(page)
        verified = await _profile_verified(page)
        bio = ""
        nickname = handle
        body_text = ""
        try:
            body_text = str(await page.locator("body").inner_text() or "")
        except Exception:
            pass
        follows_you = "Follows you" in body_text or "关注了你" in body_text
        unavailable_markers = (
            "This account doesn’t exist", "This account doesn't exist",
            "Account suspended", "账号已被冻结", "账号不存在", "此账号不存在",
        )
        profile_unavailable = any(marker in body_text for marker in unavailable_markers)
        try:
            node = page.locator('[data-testid="UserDescription"]').first
            if await node.count():
                bio = str(await node.inner_text() or "").strip()
        except Exception:
            pass
        try:
            header = page.locator('[data-testid="UserName"]').first
            if await header.count():
                raw = str(await header.inner_text() or "").strip()
                if raw:
                    nickname = raw.splitlines()[0].strip() or handle
        except Exception:
            pass

        latest_tweet_id = ""
        latest_tweet_url = ""
        pinned_fallback: tuple[str, str] | None = None
        if not profile_unavailable:
            try:
                articles = page.locator('article[data-testid="tweet"]')
                count = min(await articles.count(), 12)
                for index in range(count):
                    article = articles.nth(index)
                    raw_text = str(await article.inner_text() or "")
                    links = article.locator('a[href*="/status/"]')
                    link_count = await links.count()
                    candidate_id = ""
                    candidate_url = ""
                    for link_index in range(link_count):
                        href = str(await links.nth(link_index).get_attribute("href") or "")
                        match = re.search(r"/status/(\d+)", href)
                        if not match:
                            continue
                        path_handle = href.strip("/").split("/", 1)[0].casefold()
                        if path_handle and path_handle != handle.casefold():
                            continue
                        candidate_id = match.group(1)
                        candidate_url = (
                            href if href.startswith("http")
                            else f"https://x.com{href if href.startswith('/') else '/' + href}"
                        )
                        break
                    if not candidate_id:
                        continue
                    is_pinned = "Pinned" in raw_text or "已置顶" in raw_text
                    if not is_pinned:
                        latest_tweet_id, latest_tweet_url = candidate_id, candidate_url
                        break
                    if pinned_fallback is None:
                        pinned_fallback = (candidate_id, candidate_url)
                if not latest_tweet_id and pinned_fallback:
                    latest_tweet_id, latest_tweet_url = pinned_fallback
            except Exception:
                pass

        return {
            "handle": handle,
            "url": profile_url,
            "nickname": nickname,
            "bio": bio,
            "verified": verified,
            "relationship_state": state,
            "follows_you": follows_you,
            "profile_unavailable": profile_unavailable,
            "latest_tweet_id": latest_tweet_id,
            "latest_tweet_url": latest_tweet_url,
            "risk_marker": risk_marker or "",
        }


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
        *, on_submit=None, require_verified: bool = False,
) -> XRelationshipOutcome:
    """Follow/unfollow one X account and verify the resulting UI state."""
    action: Literal["follow", "unfollow"] = "follow" if should_follow else "unfollow"
    try:
        handle, profile_url = normalize_x_handle(target)
    except ValueError as exc:
        return XRelationshipOutcome("failed", action, "", error=str(exc))

    clicked = False
    submitted = False
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

            if should_follow and require_verified and not await _profile_verified(page):
                return XRelationshipOutcome(
                    "failed", action, handle,
                    error="quality_gate:X 目标账号不是蓝V认证，已跳过关注",
                )

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

            if callable(on_submit):
                on_submit()
            submitted = True
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
        status: Literal["failed", "uncertain"] = (
            "uncertain" if submitted or clicked else "failed")
        return XRelationshipOutcome(
            status, action, handle, changed=clicked,
            error=f"X {action} 异常: {exc!r}",
        )
