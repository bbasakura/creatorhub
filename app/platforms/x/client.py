"""Visible-browser X (Twitter) operations for CreatorHub.

The adapter deliberately uses the account's persistent BrowserManager profile.
Writes cross the submit boundary once and return ``uncertain`` when success
cannot be proven, so the queue never silently duplicates a tweet/reply.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence
from urllib.parse import quote, urlparse

from ...browser.identity import Identity
from ...browser.manager import BrowserManager
from .risk_probe import detect_x_write_risk, dismiss_x_benign_overlay

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


def _x_count(raw: str) -> int:
    text = str(raw or "").replace(",", "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB万]?)", text, re.I)
    if not match:
        return 0
    value = float(match.group(1))
    scale = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "万": 10_000}.get(match.group(2).lower(), 1)
    return int(value * scale)


def _x_epoch(raw: str) -> int:
    value = str(raw or "").strip()
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


async def _x_profile_snapshot(page: Any, base: dict | None = None) -> dict:
    profile = dict(base or {})
    handle = str(profile.get("handle") or "").strip()
    if not handle:
        profile.update(await _profile_from_page(page))
        handle = str(profile.get("handle") or "").strip()
    if handle and f"/{handle}" not in str(getattr(page, "url", "")):
        await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(700)
    try:
        followers = page.locator(f'a[href="/{handle}/verified_followers"], a[href="/{handle}/followers"]').first
        if await followers.count():
            profile["follower_count"] = _x_count(await followers.inner_text())
    except Exception:
        pass
    try:
        following = page.locator(f'a[href="/{handle}/following"]').first
        if await following.count():
            profile["following_count"] = _x_count(await following.inner_text())
    except Exception:
        pass
    try:
        avatar = page.locator('a[href$="/photo"] img').first
        if await avatar.count():
            profile["avatar"] = str(await avatar.get_attribute("src") or "")
    except Exception:
        pass
    try:
        header = page.locator('[data-testid="primaryColumn"]').first
        raw = str(await header.inner_text() or "") if await header.count() else ""
        post_match = re.search(r"([0-9.,]+(?:[KMB万])?)\s*(?:Posts?|帖子|贴文)", raw, re.I)
        if post_match:
            profile["aweme_count"] = _x_count(post_match.group(1))
    except Exception:
        pass
    profile.setdefault("follower_count", 0)
    profile.setdefault("following_count", 0)
    profile.setdefault("aweme_count", 0)
    return profile


async def fetch_x_self_profile(mgr: BrowserManager, identity: Identity) -> dict:
    async with mgr.visible_page(identity, url=X_HOME_URL) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        base = await _profile_from_page(page)
        return await _x_profile_snapshot(page, base)


async def _fill_editor(page: Any, text: str) -> Any:
    editors = page.locator('[data-testid="tweetTextarea_0"]')
    editor = None
    try:
        deadline = asyncio.get_running_loop().time() + 15.0
        while asyncio.get_running_loop().time() < deadline:
            count = await editors.count()
            for index in range(count - 1, -1, -1):
                candidate = editors.nth(index)
                try:
                    if await candidate.is_visible():
                        editor = candidate
                        break
                except Exception:
                    continue
            if editor is not None:
                break
            await page.wait_for_timeout(200)
    except Exception:
        editor = None
    if editor is None:
        raise RuntimeError("未找到 X 帖子输入框，页面可能已改版或登录失效")

    # X 的回复弹层会放置 modal mask；鼠标 click 可能被 mask 拦截。
    # DOM focus 不产生平台写副作用，也不会跨过 submit boundary。
    try:
        await editor.evaluate("el => el.focus()")
    except Exception:
        try:
            await editor.click(timeout=3000)
        except Exception as exc:
            raise RuntimeError("X 输入框无法获得焦点") from exc
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


async def _submit_once(page: Any, submitted: dict, evidence: dict, on_submit=None) -> None:
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
    risk_marker = await detect_x_write_risk(page)
    if risk_marker:
        raise RuntimeError(f"risk_blocked:X 写入前检测到平台风控/验证提示: {risk_marker}")
    if callable(on_submit):
        on_submit()
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
        *, timeout_seconds: int = 120, on_submit=None) -> tuple[bool, str, str]:
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
            risk_marker = await detect_x_write_risk(page)
            if risk_marker:
                return False, "", f"risk_blocked:X 发帖前检测到平台风控/验证提示: {risk_marker}"
            page.on("response", listener)
            try:
                await asyncio.wait_for(
                    _submit_once(page, submitted, evidence, on_submit=on_submit),
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


async def fetch_x_search(
        mgr: BrowserManager, identity: Identity, query: str,
        limit: int = 20, product: str = "Latest") -> list[dict]:
    text = str(query or "").strip()
    if not text:
        raise ValueError("X 搜索关键词不能为空")
    limit = max(1, min(80, int(limit or 20)))
    product_key = str(product or "Latest").strip().lower()
    filter_suffix = "&f=live" if product_key == "latest" else "&f=media" if product_key == "media" else ""
    url = f"https://x.com/search?q={quote(text)}&src=typed_query{filter_suffix}"
    items: list[dict] = []
    seen: set[str] = set()
    async with mgr.visible_page(identity, url=url) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        await page.wait_for_timeout(900)
        for _ in range(8):
            cards = page.locator('article[data-testid="tweet"]')
            for index in range(await cards.count()):
                card = cards.nth(index)
                try:
                    link = card.locator('a[href*="/status/"]').first
                    href = str(await link.get_attribute("href") or "")
                    match = _STATUS_RE.search(href)
                    if not match or match.group(1) in seen:
                        continue
                    tweet_id = match.group(1)
                    seen.add(tweet_id)
                    text_node = card.locator('[data-testid="tweetText"]').first
                    tweet_text = str(await text_node.inner_text() or "") if await text_node.count() else ""
                    user_node = card.locator('[data-testid="User-Name"]').first
                    user_text = str(await user_node.inner_text() or "") if await user_node.count() else ""
                    handle_match = re.search(r"@([A-Za-z0-9_]{1,15})", user_text)
                    time_node = card.locator("time").first
                    created_at = str(await time_node.get_attribute("datetime") or "") if await time_node.count() else ""
                    items.append({
                        "id": tweet_id,
                        "url": f"https://x.com/i/web/status/{tweet_id}",
                        "text": tweet_text.strip(),
                        "author": {
                            "handle": handle_match.group(1) if handle_match else "",
                            "name": user_text.splitlines()[0].strip() if user_text else "",
                            "id": "",
                        },
                        "created_at": created_at,
                        "metrics": {"reply": 0, "retweet": 0, "like": 0, "view": 0},
                    })
                    if len(items) >= limit:
                        return items
                except Exception:
                    continue
            await page.mouse.wheel(0, 1400)
            await page.wait_for_timeout(650)
    return items


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


async def _x_metric(card: Any, selector: str) -> int:
    try:
        node = card.locator(selector).first
        if not await node.count():
            return 0
        raw = str(await node.get_attribute("aria-label") or "") or str(await node.inner_text() or "")
        return _x_count(raw)
    except Exception:
        return 0


async def fetch_x_my_works(
        mgr: BrowserManager, identity: Identity, limit: int = 100) -> tuple[list[dict], dict]:
    limit = max(1, min(200, int(limit or 100)))
    async with mgr.visible_page(identity, url=X_HOME_URL) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        profile = await _x_profile_snapshot(page, await _profile_from_page(page))
        handle = str(profile.get("handle") or "").lower()
        items: list[dict] = []
        seen: set[str] = set()
        for _ in range(14):
            cards = page.locator('article[data-testid="tweet"]')
            for index in range(await cards.count()):
                card = cards.nth(index)
                try:
                    user_text = str(await card.locator('[data-testid="User-Name"]').first.inner_text() or "")
                    hm = re.search(r"@([A-Za-z0-9_]{1,15})", user_text)
                    if handle and (not hm or hm.group(1).lower() != handle):
                        continue
                    link = card.locator('a[href*="/status/"]').first
                    href = str(await link.get_attribute("href") or "")
                    match = _STATUS_RE.search(href)
                    if not match or match.group(1) in seen:
                        continue
                    tweet_id = match.group(1); seen.add(tweet_id)
                    text_node = card.locator('[data-testid="tweetText"]').first
                    desc = str(await text_node.inner_text() or "") if await text_node.count() else ""
                    time_node = card.locator("time").first
                    created = str(await time_node.get_attribute("datetime") or "") if await time_node.count() else ""
                    has_video = bool(await card.locator('video, [data-testid="videoPlayer"], [data-testid="videoComponent"]').count())
                    media_img = card.locator('img[src*="pbs.twimg.com/media"], img[src*="pbs.twimg.com/ext_tw_video_thumb"]').first
                    cover = str(await media_img.get_attribute("src") or "") if await media_img.count() else ""
                    has_image = bool(cover)
                    media_type = "video" if has_video else "images" if has_image else "text"
                    views = await _x_metric(card, 'a[href*="/analytics"], [aria-label*="View"], [aria-label*="查看"]')
                    item = {
                        "item_id": tweet_id,
                        "desc": desc.strip(),
                        "media_type": media_type,
                        "cover_url": cover,
                        "create_time": _x_epoch(created),
                        "like_count": await _x_metric(card, '[data-testid="like"], [data-testid="unlike"]'),
                        "comment_count": await _x_metric(card, '[data-testid="reply"]'),
                        "collect_count": 0,
                        "share_count": await _x_metric(card, '[data-testid="retweet"], [data-testid="unretweet"]'),
                        "play_count": views,
                        "status": "public",
                        "raw_json": json.dumps({"url": f"https://x.com/{handle}/status/{tweet_id}"}, ensure_ascii=False),
                    }
                    items.append(item)
                    if len(items) >= limit:
                        return items, profile
                except Exception:
                    continue
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(650)
        return items, profile


async def fetch_x_relationships(
        mgr: BrowserManager, identity: Identity, direction: str,
        limit: int = 300) -> tuple[list[dict], dict]:
    if direction not in {"following", "fan"}:
        raise ValueError("direction must be following or fan")
    limit = max(1, min(500, int(limit or 300)))
    async with mgr.visible_page(identity, url=X_HOME_URL) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        profile = await _x_profile_snapshot(page, await _profile_from_page(page))
        handle = str(profile.get("handle") or "").strip()
        suffix = "following" if direction == "following" else "followers"
        await page.goto(f"https://x.com/{handle}/{suffix}", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(700)
        users: list[dict] = []
        seen: set[str] = set()
        stagnant_rounds = 0
        for _ in range(16):
            rows = await page.locator('[data-testid="UserCell"]').evaluate_all("""cells => cells.map(cell => {
                const raw = (cell.innerText || '').trim();
                const desc = cell.querySelector('[data-testid="UserDescription"]');
                const img = cell.querySelector('img[src*="profile_images"]');
                const unfollow = cell.querySelector('button[data-testid$="-unfollow"]');
                return {
                    raw,
                    signature: desc ? (desc.innerText || '').trim() : '',
                    avatar: img ? (img.getAttribute('src') || '') : '',
                    following: !!unfollow,
                };
            })""")
            before = len(seen)
            for row in rows:
                try:
                    raw = str(row.get("raw") or "")
                    hm = re.search(r"@([A-Za-z0-9_]{1,15})", raw)
                    if not hm:
                        continue
                    other = hm.group(1)
                    key = other.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    lines = [line.strip() for line in raw.splitlines() if line.strip()]
                    nickname = next((line for line in lines if not line.startswith("@") and line not in {"Follow", "Following", "关注", "正在关注", "Follows you", "关注了你"}), other)
                    is_following = direction == "following" or bool(row.get("following"))
                    users.append({
                        "uid": other,
                        "sec_uid": other,
                        "nickname": nickname,
                        "avatar": str(row.get("avatar") or ""),
                        "signature": str(row.get("signature") or ""),
                        "is_mutual": bool(direction == "fan" and is_following),
                        "is_following": bool(is_following),
                        "raw_json": json.dumps({"handle": other}, ensure_ascii=False),
                    })
                    if len(users) >= limit:
                        return users, profile
                except Exception:
                    continue
            stagnant_rounds = stagnant_rounds + 1 if len(seen) == before else 0
            if stagnant_rounds >= 3:
                break
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(550)
        return users, profile


async def fetch_x_dm_conversations(
        mgr: BrowserManager, identity: Identity, limit: int = 100) -> list[dict]:
    limit = max(1, min(200, int(limit or 100)))
    async with mgr.visible_page(identity, url="https://x.com/messages") as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        await page.wait_for_timeout(900)
        convs: list[dict] = []
        seen: set[str] = set()
        links = page.locator('a[href^="/messages/"]')
        for index in range(await links.count()):
            link = links.nth(index)
            try:
                href = str(await link.get_attribute("href") or "")
                conv_id = href.split("/messages/", 1)[-1].split("?", 1)[0].strip("/")
                if not conv_id or conv_id == "compose" or conv_id in seen:
                    continue
                seen.add(conv_id)
                raw = str(await link.inner_text() or "").strip()
                lines = [line.strip() for line in raw.splitlines() if line.strip()]
                nickname = lines[0] if lines else "X 会话"
                last_text = lines[-1] if len(lines) > 1 else ""
                img = link.locator('img[src*="profile_images"]').first
                avatar = str(await img.get_attribute("src") or "") if await img.count() else ""
                time_node = link.locator("time").first
                created = str(await time_node.get_attribute("datetime") or "") if await time_node.count() else ""
                convs.append({
                    "conv_id": conv_id,
                    "peer_uid": "",
                    "peer_sec_uid": "",
                    "peer_nickname": nickname,
                    "peer_avatar": avatar,
                    "last_text": last_text,
                    "last_time": _x_epoch(created),
                    "unread_count": 0,
                    "raw_json": json.dumps({"url": f"https://x.com/messages/{conv_id}"}, ensure_ascii=False),
                })
                if len(convs) >= limit:
                    break
            except Exception:
                continue
        if not convs:
            # An absent selector is not evidence of an empty inbox. Avoid
            # reporting a successful sync when X changes its messages UI.
            raise RuntimeError(
                "X 私信列表未取得可核验结果；尚未确认空收件箱，请检查页面加载或结构变化")
        return convs


async def fetch_x_dm_history(
        mgr: BrowserManager, identity: Identity, conv_id: str,
        limit: int = 100) -> list[dict]:
    target = f"https://x.com/messages/{str(conv_id or '').strip('/')}"
    async with mgr.visible_page(identity, url=target) as page:
        if await _page_logged_out(page):
            raise RuntimeError("logged_out:X 登录态已失效，请重新登录")
        await page.wait_for_timeout(900)
        entries = page.locator('[data-testid="messageEntry"]')
        messages: list[dict] = []
        viewport = page.viewport_size or {"width": 1280}
        for index in range(max(0, await entries.count() - limit), await entries.count()):
            entry = entries.nth(index)
            try:
                text = str(await entry.inner_text() or "").strip()
                if not text:
                    continue
                time_node = entry.locator("time").first
                created = str(await time_node.get_attribute("datetime") or "") if await time_node.count() else ""
                box = await entry.bounding_box()
                direction = "out" if box and box.get("x", 0) + box.get("width", 0) / 2 > viewport.get("width", 1280) / 2 else "in"
                stable = f"{conv_id}|{created}|{text}|{direction}"
                messages.append({
                    "msg_id": "x:" + hashlib.sha1(stable.encode("utf-8")).hexdigest(),
                    "direction": direction,
                    "msg_type": "text",
                    "text": text,
                    "create_time": _x_epoch(created),
                })
            except Exception:
                continue
        return messages


async def reply_x(
        mgr: BrowserManager, identity: Identity, tweet_ref: str, text: str,
        *, timeout_seconds: int = 90, on_submit=None) -> tuple[bool, str, str]:
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
            source_link = article.locator(f'a[href*="/status/{tweet_id}"]').first
            try:
                if not await source_link.count():
                    return False, "", f"X 目标推文身份校验失败: 页面首条推文不是 {tweet_id}"
            except Exception:
                return False, "", f"X 目标推文身份校验失败: 无法确认 {tweet_id}"
            risk_marker = await detect_x_write_risk(page)
            if risk_marker:
                return False, "", f"risk_blocked:X 回复前检测到平台风控/验证提示: {risk_marker}"
            if await dismiss_x_benign_overlay(page):
                risk_marker = await detect_x_write_risk(page)
                if risk_marker:
                    return False, "", f"risk_blocked:X 回复前检测到平台风控/验证提示: {risk_marker}"
            button = article.locator('[data-testid="reply"]').first
            try:
                await button.click(timeout=8_000)
            except Exception as exc:
                return False, "", f"无法打开 X 回复框: {exc!r}"
            await _fill_editor(page, reply)
            page.on("response", listener)
            try:
                await asyncio.wait_for(
                    _submit_once(page, submitted, evidence, on_submit=on_submit),
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
