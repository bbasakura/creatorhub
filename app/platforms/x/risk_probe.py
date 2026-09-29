"""Visible X write-risk probes shared by browser write adapters."""
from __future__ import annotations

from typing import Any


X_WRITE_RISK_MARKERS = (
    "verify your identity",
    "verify your account",
    "account locked",
    "your account is locked",
    "your account is suspended",
    "account suspended",
    "temporarily limited",
    "rate limit exceeded",
    "automated behavior",
    "suspicious activity",
    "验证你的身份",
    "验证您的身份",
    "账号已锁定",
    "账户已锁定",
    "账号已被冻结",
    "账户已被冻结",
    "账号受限",
    "账户受限",
    "操作过于频繁",
)


async def dismiss_x_benign_overlay(page: Any) -> bool:
    """Dismiss known non-risk promotional overlays that block normal clicks.

    This helper intentionally ignores unknown dialogs. Callers must run
    ``detect_x_write_risk`` first; verification/lock/rate-limit surfaces are
    never auto-dismissed.
    """
    try:
        layers = page.locator('#layers').first
        if not await layers.count():
            return False
        html = str(await layers.inner_html(timeout=3000) or "").casefold()
        text = str(await layers.inner_text(timeout=3000) or "").casefold()
        known_promote = (
            "promote_popup_image" in html
            or "promote" in text
            or "推广" in text
        )
        if not known_promote:
            return False
        for selector in (
            '[data-testid="app-bar-close"]',
            'button[aria-label="Close"]',
            'button[aria-label="关闭"]',
            '[role="dialog"] button:has(svg)',
        ):
            try:
                button = layers.locator(selector).first
                if await button.count() and await button.is_visible():
                    await button.click(timeout=3000)
                    await page.wait_for_timeout(250)
                    return True
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(250)
            return True
        except Exception:
            return False
    except Exception:
        return False


async def detect_x_write_risk(page: Any) -> str:
    """Return a visible X risk/verification marker before a write boundary."""
    chunks: list[str] = []
    for selector in ('[role="dialog"]', '[data-testid="toast"]', "body"):
        try:
            node = page.locator(selector).first
            if await node.count():
                text = str(await node.inner_text(timeout=3000) or "").strip()
                if text:
                    chunks.append(text[:12000])
        except Exception:
            continue
    haystack = "\n".join(chunks).casefold()
    for marker in X_WRITE_RISK_MARKERS:
        if marker.casefold() in haystack:
            return marker
    return ""
