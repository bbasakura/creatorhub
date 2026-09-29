"""Visible-browser X (Twitter) operations for CreatorHub.

The adapter deliberately uses the account's persistent BrowserManager profile.
Writes cross the submit boundary once and return ``uncertain`` when success
cannot be proven, so the queue never silently duplicates a tweet/reply.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence
from urllib.parse import urlparse

from ...browser.identity import Identity
from ...browser.manager import BrowserManager

X_HOME_URL = "https://x.com/home"
X_COMPOSE_URL = "https://x.com/compose/post"
_X_AUTH_COOKIE = "auth_token"
_STATUS_RE = re.compile(r"/status/(\d+)")


@dataclass(frozen=True)
class XWriteOutcome:
    status: Literal["success", "failed", "uncertain"]
    result: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def legacy(self) -> tuple[bool, str, str]:
        if self.status == "success":
            return True, self.result, ""
        if self.status == "uncertain":
            return False, "", "write_uncertain:" + (
                self.error or "X 已提交但未取得明确成功证据，请先到平台核对")
        return False, "", self.error or "X 页面操作失败"


def normalize_tweet_ref(value: str) -> tuple[str, str]:
    """Return ``(tweet_id, canonical_url)`` from an id or X/Twitter URL."""
    raw = str(value or "").strip()
    if raw.isdigit():
        return raw, f"https://x.com/i/web/status/{raw}"
    try:
        parsed = urlparse(raw)
    except Exception:
        parsed = None
    if parsed and parsed.hostname:
        host = parsed.hostname.lower()
        if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            match = _STATUS_RE.search(parsed.path)
            if match:
                tweet_id = match.group(1)
                return tweet_id, f"https://x.com/i/web/status/{tweet_id}"
        raise ValueError("X 推文链接域名须为 x.com 或 twitter.com")
    match = _STATUS_RE.search(raw)
    if match:
        tweet_id = match.group(1)
        return tweet_id, f"https://x.com/i/web/status/{tweet_id}"
    raise ValueError("X 推文引用须为 tweet id 或 x.com/twitter.com 状态链接")


def _topic_tags(topics: str | Sequence[str]) -> list[str]:
    values = topics if not isinstance(topics, str) else re.split(r"[,，\s]+", topics)
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = str(value or "").strip().lstrip("#")
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def compose_x_text(title: str = "", desc: str = "", topics: str | Sequence[str] = "", *, allow_empty: bool = False) -> str:
    title = str(title or "").strip()
    desc = str(desc or "").strip()
    if title and desc and title != desc:
        text = f"{title}\n\n{desc}"
    else:
        text = desc or title
    tags = _topic_tags(topics)
    if tags:
        suffix = " ".join(f"#{tag}" for tag in tags)
        text = f"{text}\n\n{suffix}" if text else suffix
    text = text.strip()
    if not text and not allow_empty:
        raise ValueError("X 帖子正文不能为空")
    if len(text) > 280:
        raise ValueError(f"X 帖子当前为 {len(text)} 字符，超过 280 字符限制")
    return text


async def _has_x_auth(context: Any) -> bool:
    try:
        cookies = await context.cookies()
    except Exception:
        return False
    return any(c.get("name") == _X_AUTH_COOKIE and c.get("value") for c in cookies)


async def _page_logged_out(page: Any) -> bool:
    url = str(getattr(page, "url", "") or "").lower()
    if "/i/flow/login" in url or "/login" in url:
        return True
    try:
        login = page.locator('a[href="/login"], [data-testid="loginButton"]').first
        return bool(await login.count() and await login.is_visible())
    except Exception:
        return False


async def _profile_from_page(page: Any) -> dict:
    handle = ""
    nickname = ""
    try:
        link = page.locator('a[data-testid="AppTabBar_Profile_Link"]').first
        if await link.count():
            href = str(await link.get_attribute("href") or "")
            if href.startswith("/") and len(href) > 1:
                handle = href.strip("/").split("/", 1)[0]
    except Exception:
        pass
    try:
        switcher = page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').first
        if await switcher.count():
            raw = str(await switcher.inner_text() or "").strip()
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            nickname = next((line for line in lines if not line.startswith("@")), "")
            if not handle:
                handle = next((line[1:] for line in lines if line.startswith("@")), "")
    except Exception:
        pass
    return {
        "nickname": nickname or (f"@{handle}" if handle else "X 账号"),
        "handle": handle,
        "sec_uid": handle,
    }


async def interactive_x_login(
        mgr: BrowserManager, identity: Identity, timeout_seconds: int = 300,
        force_reauth: bool = False) -> tuple[bool, str, str]:
    """Open X in the account profile and wait for a real authenticated session."""
    ctx = await mgr.open_headed(identity)
    if force_reauth:
        try:
            await ctx.clear_cookies()
        except Exception:
            pass
    page = await ctx.new_page()
    state_json = ""
    nickname = ""
    logged = False
    try:
        await page.goto(X_HOME_URL, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.bring_to_front()
        except Exception:
            pass
        waited = 0.0
        while waited < max(1, timeout_seconds):
            try:
                if page.is_closed():
                    break
            except Exception:
                break
            if await _has_x_auth(ctx) and not await _page_logged_out(page):
                logged = True
                break
            await asyncio.sleep(0.5)
            waited += 0.5
        if logged:
            await page.wait_for_timeout(700)
            state_json = json.dumps(await ctx.storage_state())
            profile = await _profile_from_page(page)
            nickname = profile.get("nickname") or "X 账号"
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
    return logged, state_json, nickname


async def fetch_x_self_profile(mgr: BrowserManager, identity: Identity) -> dict:
    async with mgr.visible_page(identity, url=X_HOME_URL) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        return await _profile_from_page(page)


async def _fill_editor(page: Any, text: str) -> Any:
    editor = page.locator('[data-testid="tweetTextarea_0"]').first
    try:
        await editor.wait_for(state="visible", timeout=15_000)
    except Exception as exc:
        raise RuntimeError("未找到 X 帖子输入框，页面可能已改版或登录失效") from exc
    await editor.click()
    try:
        await editor.fill(text)
    except Exception:
        await page.keyboard.press("Control+A")
        await page.keyboard.insert_text(text)
    current = str(await editor.inner_text() or "").strip()
    if not current or text[: min(12, len(text))] not in current:
        raise RuntimeError("X 文本写入后回读校验失败")
    return editor


async def _set_media(page: Any, files: Sequence[str], media_type: str) -> list[str]:
    paths = [str(Path(p)) for p in files if p and Path(p).is_file()]
    if media_type == "text" or not paths:
        return []
    paths = paths[:1] if media_type == "video" else paths[:4]
    upload = page.locator('input[data-testid="fileInput"], input[type="file"]').first
    try:
        await upload.wait_for(state="attached", timeout=10_000)
        await upload.set_input_files(paths)
    except Exception as exc:
        raise RuntimeError("未找到 X 媒体上传控件或上传失败") from exc
    await page.wait_for_timeout(1200)
    return paths


async def _submit_once(page: Any, submitted: dict, evidence: dict) -> None:
    button = page.locator('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]').first
    try:
        await button.wait_for(state="visible", timeout=10_000)
    except Exception as exc:
        raise RuntimeError("未找到 X 发送按钮") from exc
    for _ in range(60):
        disabled = await button.get_attribute("aria-disabled")
        if disabled != "true":
            break
        await page.wait_for_timeout(250)
    else:
        raise RuntimeError("X 发送按钮一直不可用，请检查正文、媒体或页面提示")
    submitted["clicked"] = True
    await button.click()
    for _ in range(32):
        if evidence.get("accepted"):
            return
        try:
            if page.is_closed():
                return
        except Exception:
            return
        await page.wait_for_timeout(250)


def _create_tweet_listener(evidence: dict):
    def _on_response(response: Any) -> None:
        try:
            url = str(response.url or "")
            status = int(response.status or 0)
        except Exception:
            return
        if "CreateTweet" in url and 200 <= status < 300:
            evidence["accepted"] = True
    return _on_response


async def publish_x(
        mgr: BrowserManager, identity: Identity, media_type: str,
        title: str, desc: str, media_paths: Sequence[str], topics: str = "",
        *, timeout_seconds: int = 120) -> tuple[bool, str, str]:
    """Publish one X post via the account's visible persistent Chrome profile."""
    try:
        text = compose_x_text(title, desc, topics, allow_empty=bool(media_paths))
    except ValueError as exc:
        return False, "", str(exc)
    if media_type not in {"text", "media", "images", "video"}:
        return False, "", "X 内部媒体类型无效"
    submitted = {"clicked": False}
    evidence = {"accepted": False}
    listener = _create_tweet_listener(evidence)
    try:
        async with mgr.visible_page(identity, url=X_COMPOSE_URL) as page:
            if await _page_logged_out(page):
                return False, "", "logged_out:X 登录态已失效，请重新登录"
            if text:
                await _fill_editor(page, text)
            await _set_media(page, media_paths, media_type)
            page.on("response", listener)
            try:
                await asyncio.wait_for(
                    _submit_once(page, submitted, evidence),
                    timeout=max(20, timeout_seconds))
            except asyncio.TimeoutError:
                if submitted["clicked"]:
                    return XWriteOutcome(
                        "uncertain", error="X 已点击发送，但等待成功证据超时").legacy()
                return False, "", "X 发送等待超时"
            if evidence["accepted"]:
                await page.wait_for_timeout(700)
                return True, str(getattr(page, "url", "") or X_HOME_URL), ""
            if submitted["clicked"]:
                return XWriteOutcome(
                    "uncertain", error="X 已点击发送，但未捕获 CreateTweet 成功响应").legacy()
            return False, "", "X 未执行发送"
    except Exception as exc:
        status = "uncertain" if submitted["clicked"] else "failed"
        return XWriteOutcome(status, error=f"X 发布异常: {exc!r}").legacy()


async def fetch_x_following_timeline(
        mgr: BrowserManager, identity: Identity, limit: int = 20) -> list[dict]:
    """Read the authenticated Following timeline from visible X web UI."""
    limit = max(1, min(80, int(limit or 20)))
    items: list[dict] = []
    seen: set[str] = set()
    async with mgr.visible_page(identity, url=X_HOME_URL) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        for label in ("Following", "正在关注"):
            try:
                tab = page.get_by_role("tab", name=label).first
                if await tab.count() and await tab.is_visible():
                    await tab.click()
                    await page.wait_for_timeout(700)
                    break
            except Exception:
                continue
        for _ in range(8):
            cards = page.locator('article[data-testid="tweet"]')
            count = await cards.count()
            for index in range(count):
                card = cards.nth(index)
                try:
                    link = card.locator('a[href*="/status/"]').first
                    href = str(await link.get_attribute("href") or "")
                    match = _STATUS_RE.search(href)
                    if not match:
                        continue
                    tweet_id = match.group(1)
                    if tweet_id in seen:
                        continue
                    seen.add(tweet_id)
                    text_node = card.locator('[data-testid="tweetText"]').first
                    text = str(await text_node.inner_text() or "") if await text_node.count() else ""
                    user_node = card.locator('[data-testid="User-Name"]').first
                    user_text = str(await user_node.inner_text() or "") if await user_node.count() else ""
                    handle_match = re.search(r"@([A-Za-z0-9_]{1,15})", user_text)
                    time_node = card.locator("time").first
                    created_at = str(await time_node.get_attribute("datetime") or "") if await time_node.count() else ""
                    items.append({
                        "tweet_id": tweet_id,
                        "url": f"https://x.com/i/web/status/{tweet_id}",
                        "text": text.strip(),
                        "author": user_text.splitlines()[0].strip() if user_text else "",
                        "handle": handle_match.group(1) if handle_match else "",
                        "created_at": created_at,
                    })
                    if len(items) >= limit:
                        return items
                except Exception:
                    continue
            await page.mouse.wheel(0, 1400)
            await page.wait_for_timeout(700)
    return items


async def reply_x(
        mgr: BrowserManager, identity: Identity, tweet_ref: str, text: str,
        *, timeout_seconds: int = 90) -> tuple[bool, str, str]:
    reply = str(text or "").strip()
    if not reply:
        return False, "", "X 回复内容不能为空"
    if len(reply) > 280:
        return False, "", "X 回复超过 280 字符"
    try:
        tweet_id, url = normalize_tweet_ref(tweet_ref)
    except ValueError as exc:
        return False, "", str(exc)
    submitted = {"clicked": False}
    evidence = {"accepted": False}
    listener = _create_tweet_listener(evidence)
    try:
        async with mgr.visible_page(identity, url=url) as page:
            if await _page_logged_out(page):
                return False, "", "logged_out:X 登录态已失效，请重新登录"
            article = page.locator('article[data-testid="tweet"]').first
            try:
                await article.wait_for(state="visible", timeout=12_000)
            except Exception:
                return False, "", "未找到目标推文"
            button = article.locator('[data-testid="reply"]').first
            try:
                await button.click(timeout=8_000)
            except Exception as exc:
                return False, "", f"无法打开 X 回复框: {exc!r}"
            await _fill_editor(page, reply)
            page.on("response", listener)
            try:
                await asyncio.wait_for(
                    _submit_once(page, submitted, evidence),
                    timeout=max(20, timeout_seconds))
            except asyncio.TimeoutError:
                if submitted["clicked"]:
                    return XWriteOutcome(
                        "uncertain", error=f"回复 {tweet_id} 已提交但成功证据超时").legacy()
                return False, "", "X 回复等待超时"
            if evidence["accepted"]:
                return True, url, ""
            if submitted["clicked"]:
                return XWriteOutcome(
                    "uncertain", error=f"回复 {tweet_id} 已点击发送但状态待核对").legacy()
            return False, "", "X 回复未执行发送"
    except Exception as exc:
        status = "uncertain" if submitted["clicked"] else "failed"
        return XWriteOutcome(status, error=f"X 回复异常: {exc!r}").legacy()
