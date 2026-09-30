"""Read-only access to X Creator Studio official analytics and rewards progress."""
from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


ANALYTICS_URL = "https://x.com/i/account_analytics"
REWARDS_URL = "https://x.com/i/jf/creators/original_content_rewards"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_human_count(token: str) -> int | None:
    raw = str(token or "").strip().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|[KkMm])?", raw)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2) or ""
    if suffix == "万":
        value *= 10000
    elif suffix.lower() == "k":
        value *= 1000
    elif suffix.lower() == "m":
        value *= 1000000
    return int(round(value))


def _parse_rewards_progress(text: str) -> dict[str, Any]:
    body = str(text or "")
    normalized = re.sub(r"\r", "", body)
    progress = None

    segments = []
    zh = re.search(
        r"过去\s*90\s*天.*?(?:曝光|展示)(.*?)(?:回复不计入曝光|$)",
        normalized,
        flags=re.S | re.I,
    )
    if zh:
        segments.append(zh.group(1))
    en = re.search(
        r"(?:past|last)\s*90\s*days.*?(?:impression|view)(.*?)(?:repl(?:y|ies).*?(?:not|don)|$)",
        normalized,
        flags=re.S | re.I,
    )
    if en:
        segments.append(en.group(1))

    for segment in segments:
        tokens = re.findall(r"\d+(?:[.,]\d+)?\s*(?:万|[KkMm])?", segment)
        values = [_parse_human_count(token) for token in tokens]
        values = [value for value in values if value is not None]
        if values:
            progress = values[-1]
            break

    not_eligible = bool(re.search(r"不符合资[格質]|稍后再查看|not eligible", normalized, re.I))
    return {
        "qualified_impressions_90d": int(progress or 0),
        "rewards_ok": progress is not None,
        "not_eligible": not_eligible,
        "page_text": body[:12000],
    }


def _analytics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = (
        payload.get("data", {})
        .get("viewer_v2", {})
        .get("user_results", {})
        .get("result", {})
    )
    if not isinstance(result, dict):
        raise ValueError("X Creator Studio analytics response missing user result")

    totals: dict[str, int] = defaultdict(int)
    verified: dict[str, int] = defaultdict(int)
    unverified: dict[str, int] = defaultdict(int)
    daily: dict[str, dict[str, int]] = {}

    for row in result.get("current_time_series") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("engagement_type") or "")
        count = _int(row.get("count"))
        totals[kind] += count
        flag = str(row.get("is_engaging_user_verified") or "").lower()
        if flag == "true":
            verified[kind] += count
        elif flag == "false":
            unverified[kind] += count

        try:
            stamp = datetime.fromtimestamp(
                _int(row.get("timestamp")) / 1000.0, timezone.utc
            ).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            continue
        day = daily.setdefault(stamp, {})
        day[kind] = day.get(kind, 0) + count

    follows = 0
    unfollows = 0
    follow_daily: dict[str, dict[str, int]] = {}
    for row in result.get("legacy_current_follow_metrics") or []:
        if not isinstance(row, dict):
            continue
        date = str((row.get("timestamp") or {}).get("iso8601_time") or "")[:10]
        values = {}
        for metric in row.get("metric_values") or []:
            if isinstance(metric, dict):
                values[str(metric.get("metric_type") or "")] = _int(
                    metric.get("metric_value")
                )
        f = values.get("Follows", 0)
        u = values.get("Unfollows", 0)
        follows += f
        unfollows += u
        if date:
            follow_daily[date] = {"follows": f, "unfollows": u}
            day = daily.setdefault(date, {})
            day["Follows"] = f
            day["Unfollows"] = u

    def total(*names: str) -> int:
        return sum(totals.get(name, 0) for name in names)

    impressions = total("Displayed")
    profile_visits = total("ProfilePic")
    replies = total("Reply")
    likes = total("Fav")
    reposts = total("Retweet", "RetweetCreate", "Repost", "RepostCreate")
    bookmarks = total("Bookmark")
    shares = total("Share", "ShareCreate")
    quotes = total("QuoteCreate")
    details = total("Detail")
    # X does not expose the aggregate card as a standalone field in this
    # response. Sum the official engagement event series used by the overview.
    engagements = (
        profile_visits + replies + likes + reposts + bookmarks
        + shares + quotes + details
    )
    engagement_rate = (engagements / impressions) if impressions > 0 else 0.0

    daily_rows = []
    for date in sorted(daily):
        row = daily[date]
        day_impressions = _int(row.get("Displayed"))
        day_engagements = sum(
            _int(row.get(name))
            for name in (
                "ProfilePic", "Reply", "Fav", "Retweet", "RetweetCreate",
                "Repost", "RepostCreate", "Bookmark", "Share", "ShareCreate",
                "QuoteCreate", "Detail",
            )
        )
        daily_rows.append({
            "date": date,
            "impressions": day_impressions,
            "verified_impressions": 0,
            "engagements": day_engagements,
            "profile_visits": _int(row.get("ProfilePic")),
            "replies": _int(row.get("Reply")),
            "likes": _int(row.get("Fav")),
            "bookmarks": _int(row.get("Bookmark")),
            "follows": _int(row.get("Follows")),
            "unfollows": _int(row.get("Unfollows")),
            "posts": _int(row.get("TweetCreate")),
            "reply_posts": _int(row.get("ReplyCreate")),
        })

    # Fill verified impressions per day from raw current series.
    verified_by_day: dict[str, int] = defaultdict(int)
    for row in result.get("current_time_series") or []:
        if (
            isinstance(row, dict)
            and row.get("engagement_type") == "Displayed"
            and str(row.get("is_engaging_user_verified") or "").lower() == "true"
        ):
            try:
                date = datetime.fromtimestamp(
                    _int(row.get("timestamp")) / 1000.0, timezone.utc
                ).strftime("%Y-%m-%d")
                verified_by_day[date] += _int(row.get("count"))
            except (OSError, OverflowError, ValueError):
                pass
    for row in daily_rows:
        row["verified_impressions"] = verified_by_day.get(row["date"], 0)

    follower_count = _int((result.get("relationship_counts") or {}).get("followers"))
    verified_followers = _int(result.get("verified_follower_count"))
    return {
        "analytics_ok": True,
        "period_days": 7,
        "verified_followers": verified_followers,
        "follower_count": follower_count,
        "impressions": impressions,
        "verified_impressions": verified.get("Displayed", 0),
        "unverified_impressions": unverified.get("Displayed", 0),
        "engagements": engagements,
        "engagement_rate": round(engagement_rate, 6),
        "profile_visits": profile_visits,
        "replies": replies,
        "likes": likes,
        "reposts": reposts,
        "bookmarks": bookmarks,
        "shares": shares,
        "follows": follows,
        "unfollows": unfollows,
        "posts": total("TweetCreate"),
        "reply_posts": total("ReplyCreate"),
        "daily": daily_rows,
        "raw_result": result,
    }


async def fetch_creator_studio_official(browser, identity) -> dict[str, Any]:
    analytics_payload = None
    analytics_error = ""
    rewards = {"qualified_impressions_90d": 0, "rewards_ok": False, "page_text": ""}
    reward_error = ""

    # One browser lease is enough for both official pages. Keeping the same
    # authenticated page avoids paying context/profile startup twice.
    async with browser.visible_page(identity) as page:
        box: dict[str, str | None] = {"body": None}
        event = asyncio.Event()

        async def inspect(response):
            nonlocal analytics_error
            if "accountOverviewDailyQuery" not in response.url:
                return
            try:
                box["body"] = await response.text()
            except Exception as exc:
                analytics_error = f"{type(exc).__name__}: {exc}"
            finally:
                event.set()

        def on_response(response):
            if "accountOverviewDailyQuery" in response.url:
                asyncio.create_task(inspect(response))

        page.on("response", on_response)
        try:
            await page.goto(
                ANALYTICS_URL, wait_until="domcontentloaded", timeout=30000
            )
            try:
                await asyncio.wait_for(event.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            if not box["body"]:
                raise RuntimeError("未捕获 accountOverviewDailyQuery")
            analytics_payload = json.loads(str(box["body"]))
        except Exception as exc:
            analytics_error = f"{type(exc).__name__}: {exc}"

        try:
            await page.goto(
                REWARDS_URL, wait_until="domcontentloaded", timeout=30000
            )
            await page.wait_for_timeout(2500)
            text = await page.locator("body").inner_text(timeout=5000)
            rewards = _parse_rewards_progress(text)
        except Exception as exc:
            reward_error = f"{type(exc).__name__}: {exc}"

    result: dict[str, Any] = {
        "source": "x_creator_studio",
        "analytics_url": ANALYTICS_URL,
        "rewards_url": REWARDS_URL,
        "analytics_error": analytics_error,
        "rewards_error": reward_error,
        **rewards,
    }
    if analytics_payload is not None:
        result.update(_analytics_payload(analytics_payload))
        result["analytics_raw"] = analytics_payload
    else:
        result["analytics_ok"] = False
    return result
