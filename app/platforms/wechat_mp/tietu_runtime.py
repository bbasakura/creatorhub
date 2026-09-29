"""WeChat MP image-post helpers extracted from the proven batch workflow.

These helpers are intentionally narrow: they only operate inside an already
opened WeChat image-post editor. Draft success evidence remains in
``draft_safety.py`` and ``publish.py``.
"""
from __future__ import annotations

import re
from typing import Any


TITLE_SELECTOR = (
    "#js_title_main .ProseMirror:visible, "
    ".title-editor__input .ProseMirror:visible, textarea#title:visible"
)
BODY_SELECTOR = ".share-text__input .ProseMirror"


def topic_tokens(raw: str) -> list[str]:
    """Normalize comma/space separated topics to unique ``#topic`` tokens."""
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,，\s]+", raw or ""):
        token = item.strip().lstrip("#")
        if not token or token in seen:
            continue
        seen.add(token)
        result.append("#" + token)
    return result


async def replace_text_via_cdp(page: Any, selector: str, text: str) -> None:
    """Replace editor text through Chrome Input.insertText.

    WeChat's ProseMirror reacts more reliably to native text insertion than to
    direct DOM assignment/fill, especially for Chinese IME-like input.
    """
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=15000)
    await loc.scroll_into_view_if_needed(timeout=10000)
    await loc.click(timeout=10000)
    try:
        await loc.evaluate("e => e.focus()")
    except Exception:
        pass
    await page.keyboard.press("Control+A")
    await page.wait_for_timeout(80)
    await page.keyboard.press("Delete")
    await page.wait_for_timeout(120)
    session = await page.context.new_cdp_session(page)
    try:
        lines = str(text or "").split("\n")
        for index, part in enumerate(lines):
            if part:
                await session.send("Input.insertText", {"text": part})
            if index + 1 < len(lines):
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(80)
    finally:
        await session.detach()
    await page.wait_for_timeout(250)


async def append_topics_via_cdp(page: Any, topics: str) -> int:
    """Append topics one-by-one so WeChat can convert them into topic links."""
    tokens = topic_tokens(topics)
    if not tokens:
        return 0
    loc = page.locator(BODY_SELECTOR).first
    await loc.wait_for(state="visible", timeout=10000)
    await loc.evaluate("e => e.focus()")
    await page.keyboard.press("Control+End")
    await page.keyboard.press("Enter")
    await page.keyboard.press("Enter")
    session = await page.context.new_cdp_session(page)
    try:
        for token in tokens:
            await session.send("Input.insertText", {"text": token})
            await page.wait_for_timeout(160)
            await page.keyboard.press("Space")
            await page.wait_for_timeout(320)
    finally:
        await session.detach()
    try:
        return int(await page.evaluate("""(sel) => {
            const root = document.querySelector(sel);
            if (!root) return 0;
            return [...root.querySelectorAll('a, [class*=topic], [class*=link]')]
              .filter(e => (e.innerText || '').trim().startsWith('#')).length;
        }""", BODY_SELECTOR))
    except Exception:
        return 0


async def set_album(page: Any, album_name: str) -> bool:
    """Select a WeChat image-post album when one is requested."""
    album_name = (album_name or "").strip()
    if not album_name:
        return True
    try:
        opener = page.locator(
            "#js_article_tags_area .allow_click_opr, "
            "#js_article_tags_area .js_article_tags_label"
        ).first
        if not await opener.count():
            return False
        await opener.scroll_into_view_if_needed(timeout=8000)
        await opener.click(timeout=8000)
        await page.wait_for_timeout(600)
        dialog = page.locator(".album-setting-dialog:visible").last
        if not await dialog.count():
            return False
        picker = dialog.locator("input[placeholder='请选择合集']").first
        if await picker.count():
            await picker.click(timeout=8000)
            await page.wait_for_timeout(400)
        option = dialog.get_by_text(album_name, exact=True).first
        if not await option.count():
            return False
        await option.click(timeout=8000)
        confirm = dialog.get_by_role("button", name="确认", exact=True).first
        if not await confirm.count():
            confirm = dialog.locator(".weui-desktop-btn_primary").first
        await confirm.click(timeout=8000)
        await page.wait_for_timeout(700)
        text = await page.locator("#js_article_tags_area").inner_text()
        return album_name in text
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def set_claim(page: Any, claim_text: str = "个人观点") -> bool:
    """Best-effort creation-source declaration used by the proven batch flow."""
    claim_text = (claim_text or "").strip()
    if not claim_text:
        return True
    try:
        item = page.locator(".setting-group__checkbox-item").filter(
            has_text="创作来源").first
        if not await item.count():
            return False
        opener = item.locator(".allow_click_opr").first
        if not await opener.count():
            return False
        await opener.scroll_into_view_if_needed(timeout=8000)
        await opener.click(timeout=8000)
        await page.wait_for_timeout(600)
        dialog = page.locator(".weui-desktop-dialog:visible").filter(
            has_text="创作来源").last
        if not await dialog.count():
            dialog = page.locator(".weui-desktop-dialog:visible").last
        option = dialog.get_by_text(claim_text, exact=False).first
        if not await option.count():
            return False
        await option.click(timeout=8000)
        confirm = dialog.get_by_role("button", name="确认", exact=True).first
        if not await confirm.count():
            confirm = dialog.locator(".weui-desktop-btn_primary").first
        await confirm.click(timeout=8000)
        await page.wait_for_timeout(700)
        return claim_text in (await item.inner_text())
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def set_reward(page: Any) -> bool:
    """Best-effort enable the image-post reward switch when WeChat exposes it."""
    try:
        area = page.locator("#js_reward_setting_area").first
        if not await area.count() or not await area.is_visible():
            return False
        checkbox = area.locator(".js_reward_setting_checkbox").first
        if await checkbox.count() and await checkbox.is_checked():
            return True
        switch = area.locator(".setting-group__switch").first
        if not await switch.count():
            return False
        await switch.click(timeout=8000)
        await page.wait_for_timeout(700)
        dialog = page.locator(".weui-desktop-dialog:visible").filter(
            has_text="赞赏类型").last
        if not await dialog.count():
            return False
        author = dialog.get_by_text("赞赏作者", exact=False).first
        if await author.count():
            await author.click(timeout=8000)
        agreement = dialog.get_by_text("我已阅读", exact=False).first
        if await agreement.count():
            cb = agreement.locator("input").first
            checked = await cb.is_checked() if await cb.count() else False
            if not checked:
                await agreement.click(timeout=8000)
        confirm = dialog.locator(".weui-desktop-btn_primary").first
        if not await confirm.count():
            return False
        await confirm.click(timeout=8000)
        await page.wait_for_timeout(700)
        if await checkbox.count():
            return await checkbox.is_checked()
        return True
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def apply_tietu_extras(page: Any, *, album_name: str = "",
                             claim_text: str = "个人观点",
                             enable_reward: bool = True) -> dict[str, bool]:
    """Apply optional metadata without making draft saving depend on them."""
    return {
        "album": await set_album(page, album_name),
        "claim": await set_claim(page, claim_text),
        "reward": (await set_reward(page)) if enable_reward else True,
    }
