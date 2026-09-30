from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from ..db import get_session
from ..models import (
    AccountStatSnapshot,
    AccountWork,
    DouyinAccount,
    FollowEdge,
    XAccountGrowthSnapshot,
    XCreatorStudioSnapshot,
    XRevenueProfile,
    XWorkMetricSnapshot,
)


def get_or_create_revenue_profile(account_id: int) -> XRevenueProfile:
    with get_session() as session:
        row = session.exec(select(XRevenueProfile).where(
            XRevenueProfile.account_id == int(account_id)
        )).first()
        if row is None:
            row = XRevenueProfile(account_id=int(account_id))
            session.add(row)
            session.commit()
            session.refresh(row)
        session.expunge(row)
        return row


def revenue_profile_dict(row: XRevenueProfile) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "premium_active": bool(row.premium_active),
        "identity_verified": bool(row.identity_verified),
        "payout_connected": bool(row.payout_connected),
        "rewards_enrolled": bool(row.rewards_enrolled),
        "official_verified_followers": int(row.official_verified_followers or 0),
        "official_qualified_impressions_90d": int(
            row.official_qualified_impressions_90d or 0),
        "target_verified_followers": max(
            1, int(row.target_verified_followers or 500)),
        "target_qualified_impressions_90d": max(
            1, int(row.target_qualified_impressions_90d or 500000)),
        "note": str(row.note or ""),
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def creator_studio_snapshot_dict(row: XCreatorStudioSnapshot | None) -> dict:
    if row is None:
        return {
            "available": False,
            "source": "x_creator_studio",
            "daily": [],
        }
    try:
        daily = json.loads(row.daily_json or "[]")
        if not isinstance(daily, list):
            daily = []
    except Exception:
        daily = []
    return {
        "available": bool(row.analytics_ok or row.rewards_ok),
        "source": "x_creator_studio",
        "period_days": int(row.period_days or 7),
        "verified_followers": int(row.verified_followers or 0),
        "follower_count": int(row.follower_count or 0),
        "impressions": int(row.impressions or 0),
        "verified_impressions": int(row.verified_impressions or 0),
        "unverified_impressions": int(row.unverified_impressions or 0),
        "engagements": int(row.engagements or 0),
        "engagement_rate": float(row.engagement_rate or 0),
        "profile_visits": int(row.profile_visits or 0),
        "replies": int(row.replies or 0),
        "likes": int(row.likes or 0),
        "reposts": int(row.reposts or 0),
        "bookmarks": int(row.bookmarks or 0),
        "shares": int(row.shares or 0),
        "follows": int(row.follows or 0),
        "unfollows": int(row.unfollows or 0),
        "net_follows": int(row.follows or 0) - int(row.unfollows or 0),
        "posts": int(row.posts or 0),
        "reply_posts": int(row.reply_posts or 0),
        "qualified_impressions_90d": int(row.qualified_impressions_90d or 0),
        "verified_followers_eligible": bool(row.verified_followers_eligible),
        "qualified_impressions_eligible": bool(row.qualified_impressions_eligible),
        "analytics_ok": bool(row.analytics_ok),
        "rewards_ok": bool(row.rewards_ok),
        "daily": daily,
        "error": str(row.error or ""),
        "captured_at": row.captured_at.isoformat() if row.captured_at else "",
    }


def persist_creator_studio_official(account_id: int, payload: dict) -> dict:
    """Persist one official Creator Studio read and update revenue qualification fields."""
    now = datetime.utcnow()
    analytics_ok = bool(payload.get("analytics_ok"))
    rewards_ok = bool(payload.get("rewards_ok"))
    verified_followers = int(payload.get("verified_followers") or 0)
    follower_count = int(payload.get("follower_count") or 0)
    qualified_90d = int(payload.get("qualified_impressions_90d") or 0)
    errors = "; ".join(
        value for value in (
            str(payload.get("analytics_error") or "").strip(),
            str(payload.get("rewards_error") or "").strip(),
        ) if value
    )
    raw = {
        "analytics_url": payload.get("analytics_url"),
        "rewards_url": payload.get("rewards_url"),
        "analytics_ok": analytics_ok,
        "rewards_ok": rewards_ok,
        "not_eligible": bool(payload.get("not_eligible")),
    }
    with get_session() as session:
        account = session.get(DouyinAccount, int(account_id))
        if account is None or account.platform != "x":
            raise ValueError("请选择有效的 X 账号")

        row = XCreatorStudioSnapshot(
            account_id=int(account_id),
            period_days=int(payload.get("period_days") or 7),
            verified_followers=verified_followers,
            follower_count=follower_count,
            impressions=int(payload.get("impressions") or 0),
            verified_impressions=int(payload.get("verified_impressions") or 0),
            unverified_impressions=int(payload.get("unverified_impressions") or 0),
            engagements=int(payload.get("engagements") or 0),
            engagement_rate=float(payload.get("engagement_rate") or 0),
            profile_visits=int(payload.get("profile_visits") or 0),
            replies=int(payload.get("replies") or 0),
            likes=int(payload.get("likes") or 0),
            reposts=int(payload.get("reposts") or 0),
            bookmarks=int(payload.get("bookmarks") or 0),
            shares=int(payload.get("shares") or 0),
            follows=int(payload.get("follows") or 0),
            unfollows=int(payload.get("unfollows") or 0),
            posts=int(payload.get("posts") or 0),
            reply_posts=int(payload.get("reply_posts") or 0),
            qualified_impressions_90d=qualified_90d,
            verified_followers_eligible=verified_followers >= 500 if analytics_ok else False,
            qualified_impressions_eligible=qualified_90d >= 500000 if rewards_ok else False,
            analytics_ok=analytics_ok,
            rewards_ok=rewards_ok,
            daily_json=json.dumps(
                payload.get("daily") or [], ensure_ascii=False,
                separators=(",", ":")),
            raw_json=json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
            error=errors[:2000],
            captured_at=now,
        )
        session.add(row)

        profile = session.exec(select(XRevenueProfile).where(
            XRevenueProfile.account_id == int(account_id)
        )).first()
        if profile is None:
            profile = XRevenueProfile(account_id=int(account_id))
        if analytics_ok:
            profile.official_verified_followers = verified_followers
        if rewards_ok:
            profile.official_qualified_impressions_90d = qualified_90d
        profile.target_verified_followers = 500
        profile.target_qualified_impressions_90d = 500000
        if bool(payload.get("not_eligible")):
            profile.rewards_enrolled = False
        profile.updated_at = now
        session.add(profile)

        if analytics_ok and follower_count > 0:
            account.follower_count = follower_count
            session.add(account)

        session.commit()
        session.refresh(row)
        return creator_studio_snapshot_dict(row)


def _utc_epoch(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def persist_x_growth_sample(
        account_id: int, items: list[dict], profile: dict,
        *, captured_at: datetime | None = None) -> dict:
    """Persist one read-only X self sample for lifecycle and follower attribution."""
    now = captured_at or datetime.utcnow()
    cutoff_30 = _utc_epoch(now - timedelta(days=30))
    added = 0
    metric_snapshots = 0
    growth_snapshot = False

    with get_session() as session:
        account = session.get(DouyinAccount, int(account_id))
        if account is None or account.platform != "x":
            raise ValueError("请选择有效的 X 账号")

        account.nickname = profile.get("nickname") or account.nickname
        account.sec_uid = profile.get("handle") or account.sec_uid
        account.douyin_id = profile.get("handle") or account.douyin_id
        account.avatar = profile.get("avatar") or account.avatar
        if profile.get("follower_count") is not None:
            account.follower_count = int(profile.get("follower_count") or 0)
        if profile.get("following_count") is not None:
            account.following_count = int(profile.get("following_count") or 0)
        if profile.get("aweme_count") is not None:
            account.aweme_count = int(profile.get("aweme_count") or 0)
        session.add(account)

        for work in items or []:
            item_id = str(work.get("item_id") or "").strip()
            if not item_id:
                continue
            existing = session.exec(select(AccountWork).where(
                AccountWork.account_id == int(account_id),
                AccountWork.item_id == item_id,
            )).first()
            if existing:
                for key, value in work.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                existing.fetched_at = now
                session.add(existing)
            else:
                session.add(AccountWork(
                    platform="x", account_id=int(account_id),
                    fetched_at=now, **work))
                added += 1

            create_time = int(work.get("create_time") or 0)
            if not create_time or create_time < cutoff_30:
                continue
            current = (
                int(work.get("play_count") or 0),
                int(work.get("like_count") or 0),
                int(work.get("comment_count") or 0),
                int(work.get("share_count") or 0),
            )
            last = session.exec(select(XWorkMetricSnapshot).where(
                XWorkMetricSnapshot.account_id == int(account_id),
                XWorkMetricSnapshot.item_id == item_id,
            ).order_by(XWorkMetricSnapshot.captured_at.desc())).first()
            previous = (
                (
                    int(last.play_count or 0), int(last.like_count or 0),
                    int(last.comment_count or 0), int(last.share_count or 0),
                )
                if last else None
            )
            stale = (
                last is None
                or (now - last.captured_at).total_seconds() >= 1800
            )
            if previous != current or stale:
                session.add(XWorkMetricSnapshot(
                    account_id=int(account_id),
                    item_id=item_id,
                    create_time=create_time,
                    play_count=current[0],
                    like_count=current[1],
                    comment_count=current[2],
                    share_count=current[3],
                    captured_at=now,
                ))
                metric_snapshots += 1

        day = now.strftime("%Y-%m-%d")
        daily = session.exec(select(AccountStatSnapshot).where(
            AccountStatSnapshot.account_id == int(account_id),
            AccountStatSnapshot.date == day,
        )).first()
        totals = {
            "follower_count": int(account.follower_count or 0),
            "aweme_count": int(account.aweme_count or len(items or [])),
            "total_like": sum(int(w.get("like_count") or 0) for w in items or []),
            "total_comment": sum(int(w.get("comment_count") or 0) for w in items or []),
            "total_play": sum(int(w.get("play_count") or 0) for w in items or []),
        }
        if daily:
            for key, value in totals.items():
                setattr(daily, key, value)
            session.add(daily)
        else:
            session.add(AccountStatSnapshot(
                platform="x", account_id=int(account_id), date=day, **totals))

        current_growth = (
            int(account.follower_count or 0),
            int(account.following_count or 0),
            int(account.aweme_count or len(items or [])),
        )
        last_growth = session.exec(select(XAccountGrowthSnapshot).where(
            XAccountGrowthSnapshot.account_id == int(account_id)
        ).order_by(XAccountGrowthSnapshot.captured_at.desc())).first()
        previous_growth = (
            (
                int(last_growth.follower_count or 0),
                int(last_growth.following_count or 0),
                int(last_growth.post_count or 0),
            )
            if last_growth else None
        )
        growth_stale = (
            last_growth is None
            or (now - last_growth.captured_at).total_seconds() >= 1800
        )
        if previous_growth != current_growth or growth_stale:
            session.add(XAccountGrowthSnapshot(
                account_id=int(account_id),
                follower_count=current_growth[0],
                following_count=current_growth[1],
                post_count=current_growth[2],
                captured_at=now,
            ))
            growth_snapshot = True

        session.commit()

    return {
        "fetched": len(items or []),
        "added": added,
        "metric_snapshots": metric_snapshots,
        "growth_snapshot": growth_snapshot,
    }


def _raw_verified(row: FollowEdge) -> bool:
    try:
        raw = json.loads(row.raw_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return bool(raw.get("verified")) if isinstance(raw, dict) else False


def _nearest_lifecycle_snapshot(
        rows: list[XWorkMetricSnapshot], create_time: int, hours: int):
    if not rows or not create_time:
        return None
    post_at = datetime.fromtimestamp(
        int(create_time), timezone.utc).replace(tzinfo=None)
    target = post_at + timedelta(hours=hours)
    best = min(
        rows,
        key=lambda row: abs((row.captured_at - target).total_seconds()),
    )
    distance = abs((best.captured_at - target).total_seconds())
    tolerance = max(1800, int(hours * 3600 * 0.45))
    if distance > tolerance:
        return None
    age_hours = max(
        0.0, (best.captured_at - post_at).total_seconds() / 3600.0)
    return {
        "captured_at": best.captured_at.isoformat(),
        "age_hours": round(age_hours, 2),
        "views": int(best.play_count or 0),
        "likes": int(best.like_count or 0),
        "replies": int(best.comment_count or 0),
        "retweets": int(best.share_count or 0),
    }


def _metric_at(rows: list[XWorkMetricSnapshot], when: datetime):
    eligible = [row for row in rows if row.captured_at <= when]
    return eligible[-1] if eligible else None


def _classification(views: int, median_views: float) -> str:
    if median_views <= 0:
        return "积累中"
    ratio = views / median_views
    if ratio >= 2.0:
        return "爆款"
    if ratio >= 1.25:
        return "潜力"
    if ratio < 0.45:
        return "偏弱"
    return "正常"


def build_growth_dashboard(account_id: int) -> dict:
    now = datetime.utcnow()
    cutoff_90 = _utc_epoch(now - timedelta(days=90))
    cutoff_30 = _utc_epoch(now - timedelta(days=30))
    with get_session() as session:
        account = session.get(DouyinAccount, int(account_id))
        if account is None or account.platform != "x":
            raise ValueError("请选择有效的 X 账号")

        profile = session.exec(select(XRevenueProfile).where(
            XRevenueProfile.account_id == int(account_id)
        )).first()
        if profile is None:
            profile = XRevenueProfile(account_id=int(account_id))
            session.add(profile)
            session.commit()
            session.refresh(profile)
            # The commit above expires already-loaded ORM rows in SQLAlchemy.
            # Refresh the account before it leaves this session so first-open
            # dashboard rendering never touches an expired detached instance.
            session.refresh(account)

        works = session.exec(select(AccountWork).where(
            AccountWork.account_id == int(account_id),
            AccountWork.platform == "x",
        ).order_by(AccountWork.create_time.desc()).limit(300)).all()

        metric_rows = session.exec(select(XWorkMetricSnapshot).where(
            XWorkMetricSnapshot.account_id == int(account_id),
        ).order_by(XWorkMetricSnapshot.captured_at.asc())).all()

        growth_rows = session.exec(select(XAccountGrowthSnapshot).where(
            XAccountGrowthSnapshot.account_id == int(account_id),
        ).order_by(XAccountGrowthSnapshot.captured_at.asc())).all()

        creator_studio = session.exec(select(XCreatorStudioSnapshot).where(
            XCreatorStudioSnapshot.account_id == int(account_id),
        ).order_by(XCreatorStudioSnapshot.id.desc()).limit(1)).first()

        fans = session.exec(select(FollowEdge).where(
            FollowEdge.account_id == int(account_id),
            FollowEdge.platform == "x",
            FollowEdge.direction == "fan",
        )).all()

        profile_payload = revenue_profile_dict(profile)
        creator_studio_payload = creator_studio_snapshot_dict(creator_studio)

    grouped_metrics: dict[str, list[XWorkMetricSnapshot]] = defaultdict(list)
    for row in metric_rows:
        grouped_metrics[str(row.item_id)].append(row)

    recent_works = [row for row in works if int(row.create_time or 0) >= cutoff_30]
    view_values = sorted(
        int(row.play_count or 0) for row in recent_works if int(row.play_count or 0) > 0)
    median_views = (
        float(view_values[len(view_values) // 2]) if view_values else 0.0)

    lifecycle = []
    for work in recent_works[:40]:
        history = grouped_metrics.get(str(work.item_id), [])
        views = int(work.play_count or 0)
        interactions = (
            int(work.like_count or 0)
            + int(work.comment_count or 0)
            + int(work.share_count or 0)
        )
        lifecycle.append({
            "item_id": str(work.item_id),
            "text": str(work.desc or ""),
            "create_time": int(work.create_time or 0),
            "views": views,
            "likes": int(work.like_count or 0),
            "replies": int(work.comment_count or 0),
            "retweets": int(work.share_count or 0),
            "engagement_rate": (
                round(interactions / views, 6) if views > 0 else 0.0),
            "classification": _classification(views, median_views),
            "snapshot_count": len(history),
            "windows": {
                str(hours): (
                    _nearest_lifecycle_snapshot(
                        history, int(work.create_time or 0), hours)
                    or {"available": False}
                )
                for hours in (1, 3, 6, 24, 72)
            },
        })
        for value in lifecycle[-1]["windows"].values():
            if "available" not in value:
                value["available"] = True

    work_by_id = {str(row.item_id): row for row in works}
    attribution_totals: dict[str, dict] = {}
    attributed_intervals = 0
    for previous, current in zip(growth_rows, growth_rows[1:]):
        followers_delta = int(current.follower_count or 0) - int(
            previous.follower_count or 0)
        elapsed = (current.captured_at - previous.captured_at).total_seconds()
        if followers_delta <= 0 or elapsed <= 0 or elapsed > 72 * 3600:
            continue
        candidates = []
        for item_id, work in work_by_id.items():
            created = int(work.create_time or 0)
            if not created:
                continue
            created_at = datetime.fromtimestamp(
                created, timezone.utc).replace(tzinfo=None)
            if created_at > current.captured_at:
                continue
            if created_at < previous.captured_at - timedelta(hours=48):
                continue
            history = grouped_metrics.get(item_id, [])
            after = _metric_at(history, current.captured_at)
            if after is None:
                continue
            before = _metric_at(history, previous.captured_at)
            before_views = (
                int(before.play_count or 0)
                if before is not None and created_at <= previous.captured_at
                else 0
            )
            view_delta = max(0, int(after.play_count or 0) - before_views)
            if view_delta > 0:
                candidates.append((item_id, work, view_delta))
        total_view_delta = sum(row[2] for row in candidates)
        if total_view_delta <= 0:
            continue
        attributed_intervals += 1
        for item_id, work, view_delta in candidates:
            share = followers_delta * (view_delta / total_view_delta)
            bucket = attribution_totals.setdefault(item_id, {
                "item_id": item_id,
                "text": str(work.desc or ""),
                "create_time": int(work.create_time or 0),
                "estimated_followers": 0.0,
                "attributed_view_delta": 0,
                "intervals": 0,
            })
            bucket["estimated_followers"] += share
            bucket["attributed_view_delta"] += int(view_delta)
            bucket["intervals"] += 1

    attribution = sorted(
        attribution_totals.values(),
        key=lambda item: (
            item["estimated_followers"], item["attributed_view_delta"]),
        reverse=True,
    )[:20]
    for item in attribution:
        item["estimated_followers"] = round(item["estimated_followers"], 1)

    verified_synced = sum(1 for row in fans if _raw_verified(row))
    public_impressions_90d = sum(
        int(row.play_count or 0)
        for row in works
        if int(row.create_time or 0) >= cutoff_90
    )
    official_verified = int(
        creator_studio_payload.get("verified_followers")
        if creator_studio_payload.get("analytics_ok")
        else profile_payload["official_verified_followers"] or 0)
    official_impressions = int(
        creator_studio_payload.get("qualified_impressions_90d")
        if creator_studio_payload.get("rewards_ok")
        else profile_payload["official_qualified_impressions_90d"] or 0)
    target_followers = int(profile_payload["target_verified_followers"])
    target_impressions = int(
        profile_payload["target_qualified_impressions_90d"])

    return {
        "ok": True,
        "account": {
            "id": account.id,
            "handle": str(account.sec_uid or account.douyin_id or ""),
            "nickname": str(account.nickname or ""),
            "followers": int(account.follower_count or 0),
            "following": int(account.following_count or 0),
            "posts": int(account.aweme_count or len(works)),
        },
        "revenue": {
            **profile_payload,
            "official_verified_followers": official_verified,
            "official_qualified_impressions_90d": official_impressions,
            "official_source": (
                "x_creator_studio"
                if creator_studio_payload.get("available")
                else "manual_fallback"),
            "official_synced_at": creator_studio_payload.get("captured_at") or "",
            "synced_verified_followers_lower_bound": verified_synced,
            "public_impressions_90d_reference": public_impressions_90d,
            "verified_followers_progress": min(
                1.0, official_verified / target_followers)
                if target_followers else 0.0,
            "qualified_impressions_progress": min(
                1.0, official_impressions / target_impressions)
                if target_impressions else 0.0,
            "official_data_complete": bool(
                creator_studio_payload.get("available")
                or official_verified > 0 or official_impressions > 0),
            "note_scope": (
                "认证粉丝和 90 天合格曝光优先来自 X Creator Studio 官方后台；"
                "公开帖子曝光和本地关系快照仅作补充参考。"
            ),
        },
        "creator_studio": creator_studio_payload,
        "growth": {
            "snapshot_count": len(growth_rows),
            "points": [
                {
                    "captured_at": row.captured_at.isoformat(),
                    "followers": int(row.follower_count or 0),
                    "following": int(row.following_count or 0),
                    "posts": int(row.post_count or 0),
                }
                for row in growth_rows[-120:]
            ],
        },
        "lifecycle": {
            "median_views_30d": median_views,
            "items": lifecycle,
            "note": (
                "生命周期窗口来自同步时保存的真实快照；"
                "新功能上线前没有历史点，因此旧帖的 1h/3h/6h 数据不会伪造回填。"
            ),
        },
        "attribution": {
            "method": "estimated_time_weighted_view_delta",
            "intervals": attributed_intervals,
            "items": attribution,
            "note": (
                "涨粉归因为估算：把相邻账号快照之间的新增粉丝，"
                "按同时间窗内近期帖子新增曝光占比分摊；不代表 X 官方逐粉丝来源。"
            ),
        },
    }
