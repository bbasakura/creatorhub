"""CreatorHub X extension API.

Read and write operations are account-bound and reuse the existing engine gates.
Bulk controls may enqueue durable tasks, but platform writes still execute one
task at a time through the shared account locks, quotas, risk gates, and
submission-boundary semantics.
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_session
from ..models import (
    AccountActionTask, CommentTask, DouyinAccount, FollowEdge,
    PublishTask, XIntelAlert, XIntelBenchmark, XIntelDailyBrief,
    XIntelPostSnapshot, XIntelScan, XRevenueProfile, XContentOpportunity,
    XRelationshipBatch,
)
from sqlmodel import select
from ..platforms.x.client import (
    fetch_x_following_timeline,
    fetch_x_search,
    fetch_x_self_profile,
    normalize_tweet_ref,
)
from ..platforms.x.relationship import normalize_x_handle
from ..platforms.x.creator_studio import fetch_creator_studio_official
from ..platforms.x.intel_analysis import (
    black_horse_candidates, explosion_candidates, generate_digest, trend_windows,
)
from ..risk import OperationKind
from ..services.runtime_context import get_runtime
from ..services.task_queue_actions import QueueActionError, perform_queue_action
from ..services.task_events import add_task_event
from ..services.x_post_campaign import (
    load_post_campaign,
    start_post_campaign,
    stop_post_campaign,
)
from ..services.x_growth_campaign import (
    load_growth_campaign,
    parse_growth_task_metadata,
    start_growth_campaign,
    stop_growth_campaign,
)
from ..services.x_workflow import (
    create_x_post_draft, create_x_reply_draft, create_x_relationship_task,
)
from ..services.x_growth_dashboard import (
    build_growth_dashboard, persist_creator_studio_official,
)
from ..services.x_content_strategy import (
    generate_and_persist_opportunities, list_content_opportunities,
)
from ..services.x_ops_settings import (
    get_x_ops_target_count, save_x_ops_target_count,
)
from ..services.x_relationship_batches import relationship_batch_dict
from ..services.x_interaction_memory import load_x_interaction_memory
from ..services.x_intel_automation import (
    alert_dict, brief_dict, daily_brief_due, load_x_intel_automation,
    persist_explosion_alerts, save_x_intel_automation, scan_schedule,
)
from ..platforms.x.providers import x_provider_status
from ..platforms.x.agent_reach import (
    AgentReachAuthMismatch,
    AgentReachReadAdapter,
    AgentReachSchemaError,
    AgentReachUnavailable,
    AgentReachUnsupported,
)
from ..platforms.x.twikit_client import (
    TwikitAuthUnavailable, TwikitReadAdapter, TwikitUnavailable,
)
from ..platforms.x.reply_decision import decide_reply
from ..platforms.x.unreciprocated_manager import UnreciprocatedManager, REMIND_PHRASES
from ..settings import get_setting
from ..platforms.x.twikit_compat import TwikitCompatibilityError


def _can_fallback_agent_reach(exc: Exception) -> bool:
    return isinstance(exc, (
        AgentReachUnavailable,
        AgentReachAuthMismatch,
        AgentReachUnsupported,
        AgentReachSchemaError,
    ))


def _can_fallback_read(exc: Exception) -> bool:
    # Only local dependency/schema failures permit changing providers.
    # Authentication, rate limits, transport failures and unknown exceptions
    # must reach the existing risk controller without a second platform read.
    return isinstance(exc, (TwikitUnavailable, TwikitAuthUnavailable,
                            TwikitCompatibilityError, KeyError, IndexError))

router = APIRouter(prefix="/api/x", tags=["x"])


def _runtime():
    runtime = get_runtime()
    if runtime is None or runtime.browser is None:
        raise HTTPException(503, "浏览器未就绪")
    if runtime.engine is None:
        raise HTTPException(503, "引擎未就绪")
    return runtime.browser, runtime.engine


@router.get("/providers")
async def providers():
    return {"ok": True, **x_provider_status()}


class XReadQueryIn(BaseModel):
    account_id: int
    query: str = ""
    count: int = Field(default=20, ge=1, le=100)
    product: str = "Latest"


def _agent_reach_adapter(account: DouyinAccount) -> AgentReachReadAdapter:
    handle = str(getattr(account, "sec_uid", "") or "").strip().lstrip("@")
    return AgentReachReadAdapter(handle)


def _twikit_adapter(account_id: int) -> TwikitReadAdapter:
    account = _x_account(account_id)
    states = tuple(s for s in (
        getattr(account, "storage_state", ""),
        getattr(account, "creator_storage_state", ""),
    ) if s)
    try:
        return TwikitReadAdapter(
            states, proxy=getattr(account, "proxy", ""),
            user_agent=getattr(account, "ua", ""))
    except (TwikitUnavailable, TwikitAuthUnavailable) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/read/search")
async def read_search(body: XReadQueryIn):
    browser, engine = _runtime()
    account = _x_account(body.account_id)
    decision = engine.risk.preflight(body.account_id, OperationKind.READ_LIGHT)
    if not decision.allowed:
        return {"ok": True, "skipped": True, "reason": decision.reason, "items": []}
    try:
        provider = "agent_reach"
        fallback_reasons = []
        async with engine.operation_guard(
                body.account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-search:{body.account_id}:{body.query[:80]}"):
            try:
                items = await _agent_reach_adapter(account).search(
                    body.query, product=body.product, count=body.count)
            except Exception as reach_exc:
                if not _can_fallback_agent_reach(reach_exc):
                    raise
                fallback_reasons.append(type(reach_exc).__name__)
                provider = "twikit"
                try:
                    items = await _twikit_adapter(body.account_id).search(
                        body.query, product=body.product, count=body.count)
                except Exception as provider_exc:
                    if not _can_fallback_read(provider_exc):
                        raise
                    fallback_reasons.append(type(provider_exc).__name__)
                    identity = browser.identity_for(account)
                    items = await fetch_x_search(
                        browser, identity, body.query,
                        limit=body.count, product=body.product)
                    provider = "browser"
        engine.risk.record_success(body.account_id, OperationKind.READ_LIGHT)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        engine.risk.record_failure(body.account_id, OperationKind.READ_LIGHT, exc)
        raise HTTPException(400, f"X 搜索失败: {exc}") from exc
    payload = {"ok": True, "provider": provider, "items": items, "count": len(items)}
    if fallback_reasons:
        payload["fallback_reason"] = fallback_reasons[-1]
        payload["fallback_chain"] = fallback_reasons
    return payload


@router.post("/read/mentions")
async def read_mentions(body: XReadQueryIn):
    _browser, engine = _runtime()
    _x_account(body.account_id)
    decision = engine.risk.preflight(body.account_id, OperationKind.READ_LIGHT)
    if not decision.allowed:
        return {"ok": True, "skipped": True, "reason": decision.reason, "items": []}
    try:
        async with engine.operation_guard(
                body.account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-mentions:{body.account_id}"):
            items = await _twikit_adapter(body.account_id).mentions(count=body.count)
        engine.risk.record_success(body.account_id, OperationKind.READ_LIGHT)
    except HTTPException:
        raise
    except Exception as exc:
        engine.risk.record_failure(body.account_id, OperationKind.READ_LIGHT, exc)
        raise HTTPException(400, f"X mentions 读取失败: {exc}") from exc
    return {"ok": True, "provider": "twikit", "items": items, "count": len(items)}


def _x_account(account_id: int) -> DouyinAccount:
    with get_session() as session:
        account = session.get(DouyinAccount, account_id)
        if not account or account.platform != "x":
            raise HTTPException(400, "请选择有效的 X 账号")
        if account.status == "invalid" or not account.storage_state:
            raise HTTPException(400, "X 登录态无效，请先重新登录")
        session.expunge(account)
        return account


class XRevenueSettingsIn(BaseModel):
    account_id: int
    premium_active: bool | None = None
    identity_verified: bool | None = None
    payout_connected: bool | None = None
    rewards_enrolled: bool | None = None
    official_verified_followers: int | None = Field(default=None, ge=0)
    official_qualified_impressions_90d: int | None = Field(default=None, ge=0)
    target_verified_followers: int | None = Field(default=None, ge=1)
    target_qualified_impressions_90d: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/growth-dashboard")
async def growth_dashboard(account_id: int):
    _x_account(account_id)
    try:
        return build_growth_dashboard(account_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/growth-dashboard/official-sync")
async def sync_growth_dashboard_official(account_id: int):
    browser, engine = _runtime()
    account = _x_account(account_id)
    decision = engine.risk.preflight(account_id, OperationKind.READ_HEAVY)
    if not decision.allowed:
        raise HTTPException(429, decision.reason or "当前 X 官方数据读取被风控延后")

    identity = browser.identity_for(account)
    try:
        async with engine.operation_guard(
                account_id, OperationKind.READ_HEAVY,
                fallback_key=f"x-creator-studio:{account_id}"):
            payload = await fetch_creator_studio_official(browser, identity)
        if payload.get("analytics_ok") or payload.get("rewards_ok"):
            engine.risk.record_success(account_id, OperationKind.READ_HEAVY)
        else:
            raise RuntimeError(
                payload.get("analytics_error")
                or payload.get("rewards_error")
                or "X Creator Studio 未返回有效数据")
    except Exception as exc:
        engine.risk.record_failure(account_id, OperationKind.READ_HEAVY, exc)
        raise HTTPException(
            502, f"同步 X Creator Studio 官方数据失败: {exc}") from exc

    snapshot = persist_creator_studio_official(account_id, payload)
    dashboard = build_growth_dashboard(account_id)
    dashboard["official_sync"] = {
        "ok": True,
        "snapshot": snapshot,
        "analytics_error": str(payload.get("analytics_error") or ""),
        "rewards_error": str(payload.get("rewards_error") or ""),
    }
    return dashboard


@router.put("/growth-dashboard/settings")
async def growth_dashboard_settings(body: XRevenueSettingsIn):
    _x_account(body.account_id)
    with get_session() as session:
        row = session.exec(select(XRevenueProfile).where(
            XRevenueProfile.account_id == body.account_id
        )).first()
        if row is None:
            row = XRevenueProfile(account_id=body.account_id)
        for field in (
            "premium_active", "identity_verified",
            "payout_connected", "rewards_enrolled",
            "official_verified_followers",
            "official_qualified_impressions_90d",
            "target_verified_followers",
            "target_qualified_impressions_90d",
            "note",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(row, field, value)
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    return build_growth_dashboard(body.account_id)


class XOpsSettingsIn(BaseModel):
    account_id: int
    target_count: int = Field(ge=1, le=10000)


def _x_ops_account(account_id: int) -> DouyinAccount:
    with get_session() as session:
        account = session.get(DouyinAccount, int(account_id))
        if account is None or account.platform != "x":
            raise HTTPException(400, "请选择有效的 X 账号")
        session.expunge(account)
        return account


@router.put("/ops/settings")
async def save_ops_settings(body: XOpsSettingsIn):
    account = _x_ops_account(body.account_id)
    target_count = save_x_ops_target_count(
        body.account_id, body.target_count)
    return {
        "ok": True,
        "account_id": body.account_id,
        "target_count": target_count,
        "login_valid": bool(
            account.status != "invalid" and account.storage_state),
        "source": "backend",
    }


@router.get("/ops/state")
async def x_ops_state(account_id: int):
    account = _x_ops_account(account_id)
    target_count = get_x_ops_target_count(account_id)
    login_valid = bool(
        account.status != "invalid" and account.storage_state)

    growth_state = load_growth_campaign(account_id)
    post_state = load_post_campaign(account_id)
    remind_state = _remind_status_payload(account_id)

    with get_session() as session:
        growth_rows = session.exec(select(AccountActionTask).where(
            AccountActionTask.platform == "x",
            AccountActionTask.account_id == account_id,
            AccountActionTask.action == "follow",
            AccountActionTask.status.in_(["pending", "doing", "uncertain"]),
        )).all()
        growth_active = [
            row for row in growth_rows
            if parse_growth_task_metadata(row.content)
        ]

        post_rows = session.exec(select(PublishTask).where(
            PublishTask.platform == "x",
            PublishTask.account_id == account_id,
            PublishTask.status.in_(
                ["draft", "pending", "publishing", "uncertain"]),
        ).order_by(PublishTask.id.desc())).all()
        post_prefix = f"x-draft:{account_id}:client:oneclick-"
        post_active = [
            row for row in post_rows
            if str(row.source_intent_key or "").startswith(post_prefix)
        ]

        visit_rows = session.exec(select(CommentTask).where(
            CommentTask.platform == "x",
            CommentTask.account_id == account_id,
        )).all()
        visit_rows = [
            row for row in visit_rows
            if str(row.xsec_token or "").startswith(X_VISIT_TASK_PREFIX)
        ]
        visit_counts = {
            status: sum(1 for row in visit_rows if row.status == status)
            for status in (
                "draft", "pending", "doing", "done",
                "failed", "uncertain", "canceled")
        }

        follow_batch = session.exec(select(XRelationshipBatch).where(
            XRelationshipBatch.platform == "x",
            XRelationshipBatch.account_id == account_id,
            XRelationshipBatch.action == "follow",
        ).order_by(XRelationshipBatch.id.desc()).limit(1)).first()
        followback = (
            relationship_batch_dict(session, follow_batch)
            if follow_batch is not None else None
        )
        session.commit()

    growth_enabled = bool(growth_state.get("enabled"))
    post_enabled = bool(post_state.get("enabled"))
    followback_busy = bool(
        followback and followback.get("status") in {"active", "paused"})
    remind_busy = bool(
        int(remind_state.get("active") or 0)
    ) or bool(remind_state.get("rate_limited"))

    return {
        "ok": True,
        "source": "backend",
        "account_id": account_id,
        "target_count": target_count,
        "login_valid": login_valid,
        "updated_at": datetime.utcnow().isoformat(),
        "disabled": {
            "growth": not login_valid,
            "remind": (not login_valid) or remind_busy
                or remind_state.get("status") == "all_completed",
            "visit": not login_valid,
            "post": (not login_valid) or post_enabled,
            "followback": (not login_valid) or followback_busy,
        },
        "growth": {
            "state": growth_state,
            "active_tasks": [
                {
                    "id": row.id,
                    "status": row.status,
                    "handle": row.target_uid,
                    "nickname": row.target_nick,
                }
                for row in growth_active
            ],
        },
        "remind": remind_state,
        "visit": {
            "counts": visit_counts,
            "review_count": int(visit_counts.get("draft") or 0),
        },
        "post": {
            "state": post_state,
            "active_tasks": [
                {"id": row.id, "status": row.status, "text": row.desc}
                for row in post_active
            ],
        },
        "followback": followback,
    }


@router.get("/timeline")
async def timeline(account_id: int, limit: int = 20):
    browser, engine = _runtime()
    account = _x_account(account_id)
    decision = engine.risk.preflight(account_id, OperationKind.READ_LIGHT)
    if not decision.allowed:
        return {
            "ok": True,
            "skipped": True,
            "reason": decision.reason,
            "items": [],
        }
    identity = browser.identity_for(account)
    try:
        provider = "agent_reach"
        fallback_reasons = []
        async with engine.operation_guard(
                account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-timeline:{account_id}"):
            try:
                items = await _agent_reach_adapter(account).timeline(count=limit)
            except Exception as reach_exc:
                if not _can_fallback_agent_reach(reach_exc):
                    raise
                fallback_reasons.append(type(reach_exc).__name__)
                provider = "twikit"
                try:
                    states = tuple(s for s in (
                        getattr(account, "storage_state", ""),
                        getattr(account, "creator_storage_state", ""),
                    ) if s)
                    items = await TwikitReadAdapter(
                        states, proxy=getattr(account, "proxy", ""),
                        user_agent=getattr(account, "ua", "")).timeline(count=limit)
                except Exception as provider_exc:
                    if not _can_fallback_read(provider_exc):
                        raise
                    fallback_reasons.append(type(provider_exc).__name__)
                    items = await fetch_x_following_timeline(
                        browser, identity, limit=limit)
                    provider = "browser"
        engine.risk.record_success(account_id, OperationKind.READ_LIGHT)
        payload = {"ok": True, "provider": provider, "items": items, "count": len(items)}
        if fallback_reasons:
            payload["fallback_reason"] = fallback_reasons[-1]
            payload["fallback_chain"] = fallback_reasons
        return payload
    except Exception as exc:
        engine.risk.record_failure(account_id, OperationKind.READ_LIGHT, exc)
        raise HTTPException(400, f"X 时间线读取失败: {exc}") from exc


class XPostSuggestIn(BaseModel):
    category: str | None = None


@router.post("/post/suggest")
async def post_suggest(body: XPostSuggestIn = XPostSuggestIn()):
    from ..platforms.x.posting_engine import XPostingEngine
    generator = XPostingEngine()
    text = generator.generate_post(body.category)
    validation = generator.validate_post(text)
    return {"ok": bool(validation.get("valid")), "text": text,
            "validation": validation}


class XOneClickPostIn(BaseModel):
    account_id: int
    target_count: int | None = Field(default=None, ge=1, le=10000)


@router.get("/post/one-click/status")
async def one_click_post_status(account_id: int):
    _x_account(account_id)
    state = load_post_campaign(account_id)
    prefix = f"x-draft:{account_id}:client:oneclick-"
    with get_session() as session:
        rows = session.exec(select(PublishTask).where(
            PublishTask.platform == "x",
            PublishTask.account_id == account_id,
            PublishTask.status.in_(["draft", "pending", "publishing", "uncertain"]),
        ).order_by(PublishTask.id.desc())).all()
        active = [
            {
                "id": row.id,
                "status": row.status,
                "text": row.desc,
            }
            for row in rows
            if str(row.source_intent_key or "").startswith(prefix)
        ]
    return {"ok": True, "state": state, "active_tasks": active}


@router.post("/post/one-click")
async def one_click_post(body: XOneClickPostIn):
    account = _x_account(body.account_id)
    if account.status == "invalid" or not account.storage_state:
        raise HTTPException(400, "X登录态失效，请在面板手动登录后重试")

    state = load_post_campaign(body.account_id)
    if state.get("enabled"):
        return {
            "ok": True,
            "already_running": True,
            "state": state,
            "message": (
                f"一键发帖已在运行：{int(state.get('run_published') or 0)}"
                f"/{int(state.get('target_count') or 1)}"
            ),
        }

    prefix = f"x-draft:{body.account_id}:client:oneclick-"
    with get_session() as session:
        rows = session.exec(select(PublishTask).where(
            PublishTask.platform == "x",
            PublishTask.account_id == body.account_id,
            PublishTask.status == "uncertain",
        ).order_by(PublishTask.id.desc())).all()
        unresolved = next(
            (row for row in rows
             if str(row.source_intent_key or "").startswith(prefix)),
            None,
        )
    if unresolved is not None:
        return {
            "ok": False,
            "uncertain": True,
            "task_id": unresolved.id,
            "status": unresolved.status,
            "text": unresolved.desc,
            "message": "上一条一键发帖结果不确定，请先核验，未启动新一轮",
        }

    target_count = (
        save_x_ops_target_count(body.account_id, body.target_count)
        if body.target_count is not None
        else get_x_ops_target_count(body.account_id)
    )
    state = start_post_campaign(
        body.account_id, target_count=target_count)
    return {
        "ok": True,
        "started": True,
        "state": state,
        "message": f"一键发帖已启动，本轮目标 {state['target_count']} 条",
    }


@router.post("/post/one-click/stop")
async def one_click_post_stop(body: XOneClickPostIn):
    _x_account(body.account_id)
    state = stop_post_campaign(body.account_id)
    return {"ok": True, "state": state}


class XReplySuggestIn(BaseModel):
    tweet_text: str = Field(min_length=1, max_length=5000)
    author_name: str = ""


@router.post("/reply/suggest")
async def reply_suggest(body: XReplySuggestIn):
    from ..platforms.x.reply_engine import XReplyEngine
    generator = XReplyEngine(target_daily_replies=20)
    text = generator.generate_micro_reply(body.tweet_text, body.author_name)
    return {"ok": True, "text": text,
            "intent": generator.classify_intent(body.tweet_text)}


class XPostDraftIn(BaseModel):
    account_id: int
    text: str = Field(default="", max_length=5000)
    topics: str = Field(default="", max_length=500)
    media_paths: list[str] = Field(default_factory=list, max_length=4)
    intent_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")


@router.post("/post/draft")
async def post_draft(body: XPostDraftIn):
    _x_account(body.account_id)
    try:
        return create_x_post_draft(
            body.account_id, body.text, topics=body.topics,
            media_paths=body.media_paths, intent_id=body.intent_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class XReplyIn(BaseModel):
    account_id: int
    tweet_ref: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=280)
    author_handle: str = Field(default="", max_length=32)


class XReplyDraftIn(XReplyIn):
    source_text: str = Field(default="", max_length=5000)


@router.post("/reply/draft")
async def reply_draft(body: XReplyDraftIn):
    _x_account(body.account_id)
    try:
        return create_x_reply_draft(
            body.account_id, body.tweet_ref, body.text,
            author_handle=body.author_handle, source_text=body.source_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/reply")
async def send_reply(body: XReplyIn):
    _browser, engine = _runtime()
    _x_account(body.account_id)
    try:
        draft = create_x_reply_draft(
            body.account_id, body.tweet_ref, body.text,
            author_handle=body.author_handle)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if draft["status"] == "done":
        return {"ok": True, "idempotent_replay": True, **draft}
    if draft["status"] == "uncertain":
        return {"ok": False, "uncertain": True, **draft}
    try:
        result = await perform_queue_action(
            "comments", draft["task_id"], "run-now", engine=engine)
    except QueueActionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"ok": True, "queued_via": "comments", **draft, "execution": result}


class XReplyPreviewIn(BaseModel):
    account_id: int | None = None
    text: str = Field(min_length=1, max_length=4000)
    author_handle: str = Field(default="", max_length=100)
    threshold: int = Field(default=6, ge=1, le=10)
    use_ai: bool = True


@router.post("/reply/preview")
async def reply_preview(body: XReplyPreviewIn):
    ai = {}
    memory = None
    if body.account_id is not None:
        _x_account(body.account_id)
        memory = load_x_interaction_memory(body.account_id, body.author_handle)
    if body.use_ai and get_setting("ai_enabled", "0") == "1":
        ai = {
            "base_url": get_setting("ai_base_url", ""),
            "api_key": get_setting("ai_api_key", ""),
            "model": get_setting("ai_model", ""),
            "temperature": get_setting("ai_temperature", "0.35"),
            "timeout": 20,
        }
    decision = await decide_reply(
        body.text, author_handle=body.author_handle,
        ai=ai, threshold=body.threshold,
        persona=get_setting("x_reply_persona", ""),
        interaction_context=(memory.prompt_context() if memory else ""))
    return {
        "ok": True, "dry_run": True,
        "interaction_count": memory.successful_replies if memory else 0,
        **decision.as_dict(),
    }


class XVisitDraftBatchIn(BaseModel):
    account_id: int
    edge_ids: list[int] = Field(min_length=1, max_length=10000)
    target_count: int | None = Field(default=None, ge=1, le=10000)
    mode: Literal["content", "morning", "evening", "visit"] = "content"
    threshold: int = Field(default=4, ge=1, le=10)
    skip_recent_hours: int = Field(default=24, ge=0, le=720)
    max_post_age_days: int = Field(default=30, ge=1, le=365)


def _visit_preset(mode: str, tweet_id: str) -> str:
    options = {
        "morning": (
            "早呀，来串个门☀️",
            "早安，路过来看看～",
            "早上好，来留个脚印☀️",
        ),
        "evening": (
            "晚上好，来串个门🌙",
            "晚间路过，来看看～",
            "晚上来留个脚印🌙",
        ),
        "visit": (
            "来串门啦，看到这条了～",
            "路过来看看，留个脚印～",
            "来看看你最近在聊啥～",
        ),
    }
    values = options.get(mode) or options["visit"]
    seed = sum(ord(ch) for ch in str(tweet_id or ""))
    return values[seed % len(values)]


def _x_created_at(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


@router.post("/visit/drafts")
async def create_visit_drafts(body: XVisitDraftBatchIn):
    account = _x_account(body.account_id)
    target_count = (
        save_x_ops_target_count(body.account_id, body.target_count)
        if body.target_count is not None
        else get_x_ops_target_count(body.account_id)
    )
    edge_ids = list(dict.fromkeys(
        int(value) for value in body.edge_ids if int(value) > 0))[:target_count]
    if not edge_ids:
        raise HTTPException(400, "请先选择粉丝")

    with get_session() as session:
        edges = session.exec(select(FollowEdge).where(
            FollowEdge.account_id == body.account_id,
            FollowEdge.platform == "x",
            FollowEdge.direction == "fan",
            FollowEdge.id.in_(edge_ids),
        )).all()
        existing = session.exec(select(CommentTask).where(
            CommentTask.platform == "x",
            CommentTask.account_id == body.account_id,
        )).all()

    by_id = {int(edge.id): edge for edge in edges if edge.id is not None}
    active_tweet_ids = {
        str(row.aweme_id or "") for row in existing
        if row.status not in {"failed", "canceled"} and str(row.aweme_id or "")
    }
    recent_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=body.skip_recent_hours)
    recent_handles = {
        str(row.target_nick or "").strip().lstrip("@").casefold()
        for row in existing
        if row.status == "done" and row.done_at is not None
        and row.done_at >= recent_cutoff
    }

    ai = {}
    if body.mode == "content" and get_setting("ai_enabled", "0") == "1":
        ai = {
            "base_url": get_setting("ai_base_url", ""),
            "api_key": get_setting("ai_api_key", ""),
            "model": get_setting("ai_model", ""),
            "temperature": get_setting("ai_temperature", "0.35"),
            "timeout": 20,
        }
    persona = get_setting("x_reply_persona", "")
    adapter = _agent_reach_adapter(account)
    semaphore = asyncio.Semaphore(3)
    max_age = timedelta(days=body.max_post_age_days)
    now_utc = datetime.now(timezone.utc)

    async def prepare(edge_id: int) -> dict:
        edge = by_id.get(edge_id)
        if edge is None:
            return {"edge_id": edge_id, "status": "skipped", "reason": "not_fan"}
        handle = str(edge.sec_uid or edge.uid or "").strip().lstrip("@")
        if not handle:
            return {"edge_id": edge_id, "status": "skipped", "reason": "missing_handle"}
        if body.skip_recent_hours and handle.casefold() in recent_handles:
            return {
                "edge_id": edge_id, "handle": handle,
                "status": "skipped", "reason": "recent_interaction",
            }

        try:
            async with semaphore:
                posts = await adapter.user_posts(handle, count=3)
        except Exception as exc:
            return {
                "edge_id": edge_id, "handle": handle, "status": "error",
                "reason": f"read_failed:{type(exc).__name__}",
            }

        post = next((item for item in posts if str(item.get("id") or "")
                     and str(item.get("text") or "").strip()), None)
        if post is None:
            return {
                "edge_id": edge_id, "handle": handle,
                "status": "skipped", "reason": "no_recent_post",
            }

        created_at = _x_created_at(str(post.get("created_at") or ""))
        if created_at is None or now_utc - created_at > max_age:
            return {
                "edge_id": edge_id, "handle": handle,
                "status": "skipped", "reason": "post_too_old",
            }

        tweet_id = str(post.get("id") or "")
        if tweet_id in active_tweet_ids:
            return {
                "edge_id": edge_id, "handle": handle, "tweet_id": tweet_id,
                "status": "skipped", "reason": "already_queued_or_replied",
            }

        source_text = str(post.get("text") or "").strip()
        if body.mode == "content":
            memory = load_x_interaction_memory(body.account_id, handle)
            decision = await decide_reply(
                source_text, author_handle=handle, ai=ai,
                threshold=body.threshold, persona=persona,
                interaction_context=memory.prompt_context())
            if not decision.eligible or not decision.reply:
                return {
                    "edge_id": edge_id, "handle": handle, "tweet_id": tweet_id,
                    "status": "skipped", "reason": f"content_not_eligible:{decision.reason}",
                }
            reply_text = str(decision.reply).strip()[:120]
            source = decision.source
        else:
            reply_text = _visit_preset(body.mode, tweet_id)
            source = "preset"

        try:
            draft = create_x_reply_draft(
                body.account_id, str(post.get("url") or tweet_id), reply_text,
                author_handle=handle, source_text=source_text)
            task_id = int(draft.get("task_id") or 0)
            if task_id:
                with get_session() as session:
                    task = session.get(CommentTask, task_id)
                    if task is not None and not str(task.xsec_token or "").startswith(
                            X_REMIND_TASK_PREFIX):
                        task.xsec_token = f"{X_VISIT_TASK_PREFIX}{edge_id}"
                        session.add(task)
                        session.commit()
        except ValueError as exc:
            return {
                "edge_id": edge_id, "handle": handle, "tweet_id": tweet_id,
                "status": "skipped", "reason": str(exc),
            }
        return {
            "edge_id": edge_id, "handle": handle, "tweet_id": tweet_id,
            "tweet_url": str(post.get("url") or ""),
            "reply": reply_text, "source": source,
            "task_id": draft.get("task_id"), "status": "created",
            "idempotent_replay": bool(draft.get("idempotent_replay")),
        }

    results = await asyncio.gather(*(prepare(edge_id) for edge_id in edge_ids))
    created = sum(1 for item in results if item.get("status") == "created")
    errors = sum(1 for item in results if item.get("status") == "error")
    return {
        "ok": True,
        "draft_only": True,
        "target_count": target_count,
        "requested": len(edge_ids),
        "created": created,
        "skipped": len(edge_ids) - created - errors,
        "errors": errors,
        "items": results,
    }


X_VISIT_TASK_PREFIX = "x_visit:"
X_REMIND_TASK_PREFIX = "x_remind:"


class XRemindCampaignIn(BaseModel):
    account_id: int


def _remind_schedule_offset(index: int, handle: str) -> int:
    """Queue immediately; the worker owns the actual 50-70s cadence."""
    del index, handle
    return 0


def _remind_task_handle(row: CommentTask) -> str:
    marker = str(row.xsec_token or "")
    if not marker.startswith(X_REMIND_TASK_PREFIX):
        return ""
    return marker[len(X_REMIND_TASK_PREFIX):].strip().lstrip("@")


def _remind_status_payload(account_id: int) -> dict:
    mgr = UnreciprocatedManager()
    summary = mgr.get_summary()
    remaining = int(
        summary.get("status_distribution", {}).get("confirmed_unreciprocated", 0)
        or 0
    )
    with get_session() as session:
        rows = session.exec(select(CommentTask).where(
            CommentTask.platform == "x",
            CommentTask.account_id == account_id,
        )).all()
    reminder_rows = [row for row in rows if _remind_task_handle(row)]
    active_rows = [
        row for row in reminder_rows
        if row.status in {"pending", "doing", "uncertain"}
    ]
    done_rows = [row for row in reminder_rows if row.status == "done"]
    canceled_rows = [row for row in reminder_rows if row.status == "canceled"]
    failed_rows = [row for row in reminder_rows if row.status == "failed"]

    recent = []
    for info in mgr.state.get("targets", {}).values():
        if info.get("status") != "reminded_waiting_24h":
            continue
        recent.append({
            "handle": info.get("clean_handle", ""),
            "nickname": info.get("nick", ""),
            "reply_text": info.get("remind_text", ""),
            "tweet_link": info.get("remind_tweet", ""),
            "remind_time": info.get("remind_time", ""),
        })
    recent.sort(key=lambda item: item.get("remind_time", ""), reverse=True)

    rate_limited = mgr.is_rate_limited()
    remaining_minutes = 0
    if rate_limited:
        until = float(mgr.state.get("rate_limited_until", 0) or 0)
        remaining_minutes = max(
            1, int(math.ceil((until - datetime.now().timestamp()) / 60))
        )
    return {
        "ok": True,
        "status": (
            "rate_limited" if rate_limited
            else "all_completed" if remaining == 0 and not active_rows
            else "running" if active_rows
            else "ready"
        ),
        "rate_limited": rate_limited,
        "remaining_minutes": remaining_minutes,
        "reminded_total": int(summary.get("reminded_waiting_24h", 0) or 0),
        "remaining": remaining,
        "active": len(active_rows),
        "done_tasks": len(done_rows),
        "canceled_tasks": len(canceled_rows),
        "failed_tasks": len(failed_rows),
        "recent": recent[:8],
        "message": (
            "全部未回关博主已催关完毕！"
            if remaining == 0 and not active_rows else ""
        ),
    }


@router.get("/remind/status")
async def remind_campaign_status(account_id: int):
    _x_account(account_id)
    return _remind_status_payload(account_id)


@router.post("/remind/start")
async def remind_campaign_start(body: XRemindCampaignIn):
    _x_account(body.account_id)
    _browser, engine = _runtime()
    mgr = UnreciprocatedManager()

    if mgr.is_rate_limited():
        payload = _remind_status_payload(body.account_id)
        payload["message"] = (
            f"X 催关处于限流冷却中，约 {payload['remaining_minutes']} 分钟后继续"
        )
        return payload

    before = _remind_status_payload(body.account_id)
    if before["active"]:
        before["status"] = "already_running"
        before["message"] = "催关任务已在队列运行，无需重复启动"
        return before

    targets = mgr.get_confirmed_unreciprocated_targets(limit=None)
    if not targets:
        before["status"] = "all_completed"
        before["message"] = "全部未回关博主已催关完毕！"
        return before

    # Queue creation itself is non-writing. Temporary comment gaps/cooldowns are
    # enforced when each durable task reaches the worker, so clicking the button
    # can safely enqueue the whole campaign without bypassing shared risk gates.
    now = datetime.utcnow()
    queued = 0
    with get_session() as session:
        existing_rows = session.exec(select(CommentTask).where(
            CommentTask.platform == "x",
            CommentTask.account_id == body.account_id,
        )).all()
        known_handles = {
            _remind_task_handle(row).casefold()
            for row in existing_rows
            if _remind_task_handle(row)
            and row.status not in {"failed", "canceled"}
        }

        for target in targets:
            handle = str(target.get("clean_handle") or "").strip().lstrip("@")
            if not handle or handle.casefold() in known_handles:
                continue
            nick = str(target.get("nick") or handle).strip()
            phrase_index = sum(ord(ch) for ch in handle) % len(REMIND_PHRASES)
            reply_text = REMIND_PHRASES[phrase_index]
            offset = _remind_schedule_offset(queued, handle)
            task = CommentTask(
                platform="x",
                account_id=body.account_id,
                aweme_id=f"remind:{handle}",
                target_comment_id="",
                xsec_token=f"{X_REMIND_TASK_PREFIX}{handle}",
                target_nick=handle,
                target_text=nick[:200],
                content=reply_text,
                scheduled_at=now + timedelta(seconds=offset),
                status="pending",
                method="browser",
            )
            session.add(task)
            session.flush()
            add_task_event(
                session, queue_type="comments", row_id=task.id,
                event_type="remind:queued", from_status="", to_status="pending",
                actor="x_remind",
                detail=(
                    f"未回关催关任务已入队：@{handle}，"
                    f"第 {queued + 1} 位；worker 按 50-70 秒随机节奏执行"
                ),
            )
            known_handles.add(handle.casefold())
            queued += 1
        session.commit()

    payload = _remind_status_payload(body.account_id)
    payload.update({
        "status": "queued" if queued else payload["status"],
        "queued": queued,
        "pacing": "每位随机50~70秒；不叠加旧COMMENT小时/每日额度；平台限流后冷却15分钟",
        "message": (
            f"已加入 {queued} 位未回关博主到催关队列"
            if queued else "没有新的未回关博主需要入队"
        ),
    })
    return payload


class XIntelBenchmarkIn(BaseModel):
    account_id: int
    handle: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=300)


class XIntelBenchmarkUpdateIn(BaseModel):
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class XIntelScanIn(BaseModel):
    account_id: int
    posts_per_account: int = Field(default=5, ge=1, le=10)
    max_accounts: int = Field(default=30, ge=1, le=50)


class XIntelDigestIn(BaseModel):
    account_id: int
    scan_id: int | None = None
    force: bool = False
    max_followers: int = Field(default=50000, ge=100, le=10000000)


class XContentOpportunityGenerateIn(BaseModel):
    account_id: int
    scan_id: int | None = None
    count: int = Field(default=3, ge=1, le=6)


class XIntelAutomationIn(BaseModel):
    account_id: int
    enabled: bool = False
    interval_hours: int = Field(default=3, ge=1, le=24)
    posts_per_account: int = Field(default=5, ge=1, le=10)
    max_accounts: int = Field(default=30, ge=1, le=50)
    daily_brief_enabled: bool = True
    daily_brief_hour: int = Field(default=20, ge=0, le=23)
    notify_explosions: bool = True
    notify_daily_brief: bool = True
    auto_opportunities_enabled: bool = False
    auto_draft_count: int = Field(default=3, ge=1, le=6)
    explosion_min_views_per_hour: float = Field(default=300.0, ge=1.0, le=10000000.0)
    explosion_min_view_delta: int = Field(default=800, ge=1, le=100000000)
    explosion_min_efficiency: float = Field(default=0.5, ge=0.0, le=100000.0)
    explosion_min_engagement_rate: float = Field(default=0.02, ge=0.0, le=1.0)


def _intel_benchmark_dict(row: XIntelBenchmark) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "handle": row.handle,
        "nickname": row.nickname,
        "note": row.note,
        "avatar": row.avatar,
        "follower_count": row.follower_count,
        "following_count": row.following_count,
        "tweet_count": row.tweet_count,
        "verified": bool(row.verified),
        "enabled": bool(row.enabled),
        "last_synced_at": (
            row.last_synced_at.isoformat() if row.last_synced_at else None),
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _intel_scan_dict(row: XIntelScan | None) -> dict | None:
    if row is None:
        return None
    requested = int(row.requested_accounts or 0)
    success = int(row.successful_accounts or 0)
    digest = None
    if row.summary_json:
        try:
            parsed = json.loads(row.summary_json)
            if isinstance(parsed, dict):
                digest = parsed
        except Exception:
            digest = None
    return {
        "id": row.id,
        "account_id": row.account_id,
        "status": row.status,
        "requested_accounts": requested,
        "successful_accounts": success,
        "failed_accounts": int(row.failed_accounts or 0),
        "post_count": int(row.post_count or 0),
        "posts_per_account": int(row.posts_per_account or 0),
        "coverage": round(success * 100 / requested, 1) if requested else 0.0,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error": row.error,
        "digest": digest,
        "summary_source": row.summary_source or "",
        "summary_generated_at": (
            row.summary_generated_at.isoformat()
            if row.summary_generated_at else None),
    }


def _intel_post_dict(
        row: XIntelPostSnapshot,
        trends: dict | None = None) -> dict:
    return {
        "id": row.id,
        "scan_id": row.scan_id,
        "benchmark_id": row.benchmark_id,
        "tweet_id": row.tweet_id,
        "tweet_url": row.tweet_url,
        "author_handle": row.author_handle,
        "author_name": row.author_name,
        "author_verified": bool(row.author_verified),
        "author_followers": int(row.author_followers or 0),
        "text": row.text,
        "posted_at": row.posted_at,
        "view_count": int(row.view_count or 0),
        "like_count": int(row.like_count or 0),
        "reply_count": int(row.reply_count or 0),
        "retweet_count": int(row.retweet_count or 0),
        "engagement_rate": float(row.engagement_rate or 0),
        "exposure_efficiency": float(row.exposure_efficiency or 0),
        "radar_score": float(row.radar_score or 0),
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "trends": trends or {
            "3": {"available": False},
            "6": {"available": False},
            "24": {"available": False},
        },
    }


def _intel_enriched_items(session, rows: list[XIntelPostSnapshot]) -> list[dict]:
    if not rows:
        return []
    tweet_ids = list({
        str(row.tweet_id or "") for row in rows if str(row.tweet_id or "")})
    history_by_tweet: dict[str, list[XIntelPostSnapshot]] = {}
    if tweet_ids:
        history = session.exec(select(XIntelPostSnapshot).where(
            XIntelPostSnapshot.account_id == rows[0].account_id,
            XIntelPostSnapshot.tweet_id.in_(tweet_ids),
        )).all()
        for snapshot in history:
            history_by_tweet.setdefault(snapshot.tweet_id, []).append(snapshot)
    return [
        _intel_post_dict(
            row,
            trend_windows(row, history_by_tweet.get(row.tweet_id, [])))
        for row in rows
    ]


def _intel_time(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _intel_metrics(post: dict, followers: int) -> dict:
    metrics = post.get("metrics") if isinstance(post.get("metrics"), dict) else {}
    views = max(0, int(metrics.get("view") or 0))
    likes = max(0, int(metrics.get("like") or 0))
    replies = max(0, int(metrics.get("reply") or 0))
    retweets = max(0, int(metrics.get("retweet") or 0))
    weighted = likes + replies * 2 + retweets * 2
    engagement_rate = weighted / views if views else 0.0
    efficiency = views / followers if followers > 0 else 0.0
    posted = _intel_time(str(post.get("created_at") or ""))
    age_hours = 9999.0
    if posted:
        age_hours = max(
            0.0, (datetime.now(timezone.utc) - posted).total_seconds() / 3600)
    freshness = max(0.0, 1.0 - min(age_hours, 48.0) / 48.0)
    # Internal comparison score for the same scan only. It combines reach,
    # weighted engagement, follower-normalized exposure and freshness.
    score = (
        math.log10(views + 1) * 30.0
        + math.log10(weighted + 1) * 18.0
        + min(40.0, math.log10(efficiency + 1) * 25.0)
        + freshness * 15.0
    )
    return {
        "views": views,
        "likes": likes,
        "replies": replies,
        "retweets": retweets,
        "engagement_rate": round(engagement_rate, 6),
        "efficiency": round(efficiency, 4),
        "score": round(score, 2),
    }


@router.get("/intel/benchmarks")
async def list_intel_benchmarks(account_id: int):
    _x_account(account_id)
    with get_session() as session:
        rows = session.exec(select(XIntelBenchmark).where(
            XIntelBenchmark.account_id == account_id
        ).order_by(XIntelBenchmark.enabled.desc(), XIntelBenchmark.id.asc())).all()
        return [_intel_benchmark_dict(row) for row in rows]


@router.post("/intel/benchmarks")
async def create_intel_benchmark(body: XIntelBenchmarkIn):
    _browser, engine = _runtime()
    account = _x_account(body.account_id)
    handle, _profile_url = normalize_x_handle(body.handle)
    with get_session() as session:
        existing = session.exec(select(XIntelBenchmark).where(
            XIntelBenchmark.account_id == body.account_id)).all()
        if any(row.handle.casefold() == handle.casefold() for row in existing):
            raise HTTPException(409, f"@{handle} 已在对标账号池")

    decision = engine.risk.preflight(body.account_id, OperationKind.READ_LIGHT)
    if not decision.allowed:
        raise HTTPException(429, decision.reason or "当前读取被风控延后")
    try:
        async with engine.operation_guard(
                body.account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-intel-profile:{body.account_id}:{handle.casefold()}"):
            profile = await _agent_reach_adapter(account).user_profile(handle)
        engine.risk.record_success(body.account_id, OperationKind.READ_LIGHT)
    except Exception as exc:
        engine.risk.record_failure(
            body.account_id, OperationKind.READ_LIGHT, exc)
        raise HTTPException(400, f"读取 @{handle} 资料失败: {exc}") from exc

    now = datetime.utcnow()
    with get_session() as session:
        row = XIntelBenchmark(
            account_id=body.account_id,
            handle=str(profile.get("handle") or handle),
            nickname=str(profile.get("nickname") or handle),
            note=body.note.strip(),
            avatar=str(profile.get("avatar") or ""),
            follower_count=int(profile.get("followers") or 0),
            following_count=int(profile.get("following") or 0),
            tweet_count=int(profile.get("tweets") or 0),
            verified=bool(profile.get("verified")),
            enabled=True,
            last_synced_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "benchmark": _intel_benchmark_dict(row)}


@router.put("/intel/benchmarks/{benchmark_id}")
async def update_intel_benchmark(
        benchmark_id: int, body: XIntelBenchmarkUpdateIn):
    with get_session() as session:
        row = session.get(XIntelBenchmark, benchmark_id)
        if not row:
            raise HTTPException(404, "对标账号不存在")
        _x_account(row.account_id)
        if body.enabled is not None:
            row.enabled = bool(body.enabled)
        if body.note is not None:
            row.note = body.note.strip()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "benchmark": _intel_benchmark_dict(row)}


@router.delete("/intel/benchmarks/{benchmark_id}")
async def delete_intel_benchmark(benchmark_id: int):
    with get_session() as session:
        row = session.get(XIntelBenchmark, benchmark_id)
        if not row:
            raise HTTPException(404, "对标账号不存在")
        _x_account(row.account_id)
        session.delete(row)
        session.commit()
    return {"ok": True}


@router.post("/intel/benchmarks/{benchmark_id}/refresh")
async def refresh_intel_benchmark(benchmark_id: int):
    _browser, engine = _runtime()
    with get_session() as session:
        row = session.get(XIntelBenchmark, benchmark_id)
        if not row:
            raise HTTPException(404, "对标账号不存在")
        account_id, handle = row.account_id, row.handle
    account = _x_account(account_id)
    decision = engine.risk.preflight(account_id, OperationKind.READ_LIGHT)
    if not decision.allowed:
        raise HTTPException(429, decision.reason or "当前读取被风控延后")
    try:
        async with engine.operation_guard(
                account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-intel-profile:{account_id}:{handle.casefold()}"):
            profile = await _agent_reach_adapter(account).user_profile(handle)
        engine.risk.record_success(account_id, OperationKind.READ_LIGHT)
    except Exception as exc:
        engine.risk.record_failure(account_id, OperationKind.READ_LIGHT, exc)
        with get_session() as session:
            row = session.get(XIntelBenchmark, benchmark_id)
            if row:
                row.last_error = str(exc)[:1000]
                session.add(row)
                session.commit()
        raise HTTPException(400, f"刷新 @{handle} 失败: {exc}") from exc

    with get_session() as session:
        row = session.get(XIntelBenchmark, benchmark_id)
        row.handle = str(profile.get("handle") or handle)
        row.nickname = str(profile.get("nickname") or row.handle)
        row.avatar = str(profile.get("avatar") or "")
        row.follower_count = int(profile.get("followers") or 0)
        row.following_count = int(profile.get("following") or 0)
        row.tweet_count = int(profile.get("tweets") or 0)
        row.verified = bool(profile.get("verified"))
        row.last_synced_at = datetime.utcnow()
        row.last_error = ""
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "benchmark": _intel_benchmark_dict(row)}


@router.get("/intel/radar")
async def get_intel_radar(account_id: int, scan_id: int | None = None):
    _x_account(account_id)
    with get_session() as session:
        scan = session.get(XIntelScan, scan_id) if scan_id else session.exec(
            select(XIntelScan).where(
                XIntelScan.account_id == account_id
            ).order_by(XIntelScan.id.desc()).limit(1)).first()
        if not scan or scan.account_id != account_id:
            return {"ok": True, "scan": None, "items": []}
        rows = session.exec(select(XIntelPostSnapshot).where(
            XIntelPostSnapshot.scan_id == scan.id
        ).order_by(
            XIntelPostSnapshot.radar_score.desc(),
            XIntelPostSnapshot.view_count.desc(),
        )).all()
        return {
            "ok": True,
            "scan": _intel_scan_dict(scan),
            "items": _intel_enriched_items(session, rows),
        }


@router.get("/intel/automation")
async def get_intel_automation(account_id: int):
    account = _x_account(account_id)
    cfg = load_x_intel_automation(account_id)
    return {
        "ok": True,
        "config": cfg,
        "schedule": scan_schedule(account_id, cfg),
        "daily_brief": daily_brief_due(account, cfg),
    }


@router.put("/intel/automation")
async def update_intel_automation(body: XIntelAutomationIn):
    account = _x_account(body.account_id)
    cfg = save_x_intel_automation(body.account_id, body.model_dump(exclude={"account_id"}))
    return {
        "ok": True,
        "config": cfg,
        "schedule": scan_schedule(body.account_id, cfg),
        "daily_brief": daily_brief_due(account, cfg),
    }


@router.get("/intel/alerts")
async def list_intel_alerts(account_id: int, limit: int = 30):
    _x_account(account_id)
    limit = max(1, min(200, int(limit or 30)))
    with get_session() as session:
        rows = session.exec(select(XIntelAlert).where(
            XIntelAlert.account_id == account_id
        ).order_by(XIntelAlert.id.desc()).limit(limit)).all()
        return {"ok": True, "items": [alert_dict(row) for row in rows]}


@router.get("/intel/daily-briefs")
async def list_intel_daily_briefs(account_id: int, limit: int = 14):
    _x_account(account_id)
    limit = max(1, min(90, int(limit or 14)))
    with get_session() as session:
        rows = session.exec(select(XIntelDailyBrief).where(
            XIntelDailyBrief.account_id == account_id
        ).order_by(XIntelDailyBrief.id.desc()).limit(limit)).all()
        return {"ok": True, "items": [brief_dict(row) for row in rows]}


@router.get("/intel/opportunities")
async def list_intel_opportunities(account_id: int, limit: int = 30):
    _x_account(account_id)
    return {
        "ok": True,
        "items": list_content_opportunities(
            account_id, max(1, min(100, int(limit or 30)))),
    }


@router.post("/intel/opportunities/generate")
async def generate_intel_opportunities(body: XContentOpportunityGenerateIn):
    _x_account(body.account_id)
    with get_session() as session:
        scan = session.get(XIntelScan, body.scan_id) if body.scan_id else session.exec(
            select(XIntelScan).where(
                XIntelScan.account_id == body.account_id,
                XIntelScan.status.in_(["done", "partial"]),
                XIntelScan.post_count > 0,
            ).order_by(XIntelScan.id.desc()).limit(1)).first()
        if not scan or scan.account_id != body.account_id:
            raise HTTPException(404, "暂无可生成内容机会的 X 情报扫描")
        rows = session.exec(select(XIntelPostSnapshot).where(
            XIntelPostSnapshot.scan_id == scan.id
        )).all()
        items = _intel_enriched_items(session, rows)
        scan_id = int(scan.id)
        scan_payload = _intel_scan_dict(scan) or {}
        digest = scan_payload.get("digest") or {}

    if not items:
        raise HTTPException(400, "本轮扫描没有可用于选题的帖子")

    if not digest:
        result = await generate_intel_digest(XIntelDigestIn(
            account_id=body.account_id,
            scan_id=scan_id,
            force=False,
            max_followers=50000,
        ))
        digest = ((result or {}).get("scan") or {}).get("digest") or {}
    if not digest:
        raise HTTPException(500, "X 情报摘要生成失败，无法建立内容机会")

    ai = {}
    if get_setting("ai_enabled", "0") == "1":
        ai = {
            "base_url": get_setting("ai_base_url", ""),
            "api_key": get_setting("ai_api_key", ""),
            "model": get_setting("ai_model", ""),
            "temperature": get_setting("ai_temperature", "0.45"),
            "timeout": 45,
        }
    opportunities = await generate_and_persist_opportunities(
        body.account_id,
        scan_id,
        items,
        digest,
        ai,
        count=body.count,
        force=False,
    )
    return {
        "ok": True,
        "scan_id": scan_id,
        "count": len(opportunities),
        "items": opportunities,
        "mode": "draft_only",
        "message": "已生成原创内容机会并进入待确认草稿；不会自动发布到 X",
    }


@router.get("/intel/black-horses")
async def get_intel_black_horses(
        account_id: int, scan_id: int | None = None,
        max_followers: int = 50000, limit: int = 20):
    _x_account(account_id)
    max_followers = max(100, min(10000000, int(max_followers or 50000)))
    limit = max(1, min(100, int(limit or 20)))
    with get_session() as session:
        scan = session.get(XIntelScan, scan_id) if scan_id else session.exec(
            select(XIntelScan).where(
                XIntelScan.account_id == account_id
            ).order_by(XIntelScan.id.desc()).limit(1)).first()
        if not scan or scan.account_id != account_id:
            return {
                "ok": True, "scan": None, "max_followers": max_followers,
                "items": [],
            }
        rows = session.exec(select(XIntelPostSnapshot).where(
            XIntelPostSnapshot.scan_id == scan.id
        )).all()
        items = _intel_enriched_items(session, rows)
        horses = black_horse_candidates(
            items, max_followers=max_followers, limit=limit)
        return {
            "ok": True,
            "scan": _intel_scan_dict(scan),
            "max_followers": max_followers,
            "definition": (
                f"候选黑马仅从本轮对标池中粉丝不超过 {max_followers} 的账号里计算；"
                "综合帖均曝光、曝光效率、互动和已有增速快照，不代表全X排名。"),
            "items": horses,
        }


@router.post("/intel/digest")
async def generate_intel_digest(body: XIntelDigestIn):
    _x_account(body.account_id)
    with get_session() as session:
        scan = session.get(XIntelScan, body.scan_id) if body.scan_id else session.exec(
            select(XIntelScan).where(
                XIntelScan.account_id == body.account_id
            ).order_by(XIntelScan.id.desc()).limit(1)).first()
        if not scan or scan.account_id != body.account_id:
            raise HTTPException(404, "暂无可总结的X情报扫描")
        if scan.summary_json and not body.force:
            return {
                "ok": True,
                "scan": _intel_scan_dict(scan),
                "cached": True,
            }
        rows = session.exec(select(XIntelPostSnapshot).where(
            XIntelPostSnapshot.scan_id == scan.id
        )).all()
        items = _intel_enriched_items(session, rows)
        scan_id = int(scan.id)

    if not items:
        raise HTTPException(400, "本轮扫描没有可总结的帖子")

    horses = black_horse_candidates(
        items, max_followers=body.max_followers, limit=20)
    ai = {}
    if get_setting("ai_enabled", "0") == "1":
        ai = {
            "base_url": get_setting("ai_base_url", ""),
            "api_key": get_setting("ai_api_key", ""),
            "model": get_setting("ai_model", ""),
            "temperature": get_setting("ai_temperature", "0.25"),
            "timeout": 30,
        }
    digest, source = await generate_digest(items, horses, ai)
    now = datetime.utcnow()
    with get_session() as session:
        scan = session.get(XIntelScan, scan_id)
        if not scan:
            raise HTTPException(404, "扫描记录已不存在")
        scan.summary_json = json.dumps(
            digest, ensure_ascii=False, separators=(",", ":"))
        scan.summary_source = source
        scan.summary_generated_at = now
        session.add(scan)
        session.commit()
        session.refresh(scan)
        return {
            "ok": True,
            "scan": _intel_scan_dict(scan),
            "cached": False,
        }


@router.post("/intel/scan")
async def scan_x_intel(body: XIntelScanIn):
    _browser, engine = _runtime()
    account = _x_account(body.account_id)
    with get_session() as session:
        rows = session.exec(select(XIntelBenchmark).where(
            XIntelBenchmark.account_id == body.account_id,
            XIntelBenchmark.enabled == True,  # noqa: E712
        ).order_by(XIntelBenchmark.id.asc())).all()
        selected = rows[:body.max_accounts]
        benchmark_specs = [{
            "id": row.id,
            "handle": row.handle,
            "nickname": row.nickname,
            "avatar": row.avatar,
            "followers": row.follower_count,
            "following": row.following_count,
            "tweets": row.tweet_count,
            "verified": bool(row.verified),
            "last_synced_at": row.last_synced_at,
        } for row in selected]
        if not benchmark_specs:
            raise HTTPException(400, "请先添加并启用至少一个对标账号")
        scan = XIntelScan(
            account_id=body.account_id,
            status="running",
            requested_accounts=len(benchmark_specs),
            posts_per_account=body.posts_per_account,
        )
        session.add(scan)
        session.commit()
        session.refresh(scan)
        scan_id = int(scan.id)

    decision = engine.risk.preflight(body.account_id, OperationKind.READ_HEAVY)
    if not decision.allowed:
        with get_session() as session:
            scan = session.get(XIntelScan, scan_id)
            scan.status = "failed"
            scan.error = decision.reason or "当前读取被风控延后"
            scan.finished_at = datetime.utcnow()
            session.add(scan)
            session.commit()
        raise HTTPException(429, decision.reason or "当前读取被风控延后")

    adapter = _agent_reach_adapter(account)
    semaphore = asyncio.Semaphore(3)
    refresh_cutoff = datetime.utcnow() - timedelta(hours=6)

    async def read_benchmark(spec: dict) -> dict:
        handle = str(spec["handle"])
        profile = {
            "handle": handle,
            "nickname": spec.get("nickname") or handle,
            "avatar": spec.get("avatar") or "",
            "followers": int(spec.get("followers") or 0),
            "following": int(spec.get("following") or 0),
            "tweets": int(spec.get("tweets") or 0),
            "verified": bool(spec.get("verified")),
        }
        try:
            async with semaphore:
                last_synced = spec.get("last_synced_at")
                if not last_synced or last_synced < refresh_cutoff:
                    profile = await adapter.user_profile(handle)
                posts = await adapter.user_posts(
                    str(profile.get("handle") or handle),
                    count=body.posts_per_account)
            return {
                "ok": True,
                "benchmark_id": spec["id"],
                "profile": profile,
                "posts": posts,
            }
        except Exception as exc:
            return {
                "ok": False,
                "benchmark_id": spec["id"],
                "handle": handle,
                "error": f"{type(exc).__name__}: {exc}",
            }

    try:
        async with engine.operation_guard(
                body.account_id, OperationKind.READ_HEAVY,
                fallback_key=f"x-intel-scan:{body.account_id}"):
            results = await asyncio.gather(
                *(read_benchmark(spec) for spec in benchmark_specs))
        engine.risk.record_success(body.account_id, OperationKind.READ_HEAVY)
    except Exception as exc:
        engine.risk.record_failure(body.account_id, OperationKind.READ_HEAVY, exc)
        with get_session() as session:
            scan = session.get(XIntelScan, scan_id)
            scan.status = "failed"
            scan.error = str(exc)[:1000]
            scan.finished_at = datetime.utcnow()
            session.add(scan)
            session.commit()
        raise HTTPException(400, f"X 情报扫描失败: {exc}") from exc

    successful = sum(1 for result in results if result.get("ok"))
    failed = len(results) - successful
    now = datetime.utcnow()
    snapshots: list[XIntelPostSnapshot] = []

    with get_session() as session:
        for result in results:
            benchmark = session.get(
                XIntelBenchmark, int(result["benchmark_id"]))
            if benchmark is None:
                continue
            if not result.get("ok"):
                benchmark.last_error = str(result.get("error") or "")[:1000]
                session.add(benchmark)
                continue

            profile = result.get("profile") or {}
            benchmark.handle = str(profile.get("handle") or benchmark.handle)
            benchmark.nickname = str(
                profile.get("nickname") or benchmark.nickname or benchmark.handle)
            benchmark.avatar = str(profile.get("avatar") or benchmark.avatar)
            benchmark.follower_count = int(
                profile.get("followers") or benchmark.follower_count or 0)
            benchmark.following_count = int(
                profile.get("following") or benchmark.following_count or 0)
            benchmark.tweet_count = int(
                profile.get("tweets") or benchmark.tweet_count or 0)
            benchmark.verified = bool(
                profile.get("verified") or benchmark.verified)
            benchmark.last_synced_at = now
            benchmark.last_error = ""
            session.add(benchmark)

            for post in result.get("posts") or []:
                tweet_id = str(post.get("id") or "")
                if not tweet_id:
                    continue
                metrics = _intel_metrics(
                    post, int(benchmark.follower_count or 0))
                author = (
                    post.get("author")
                    if isinstance(post.get("author"), dict) else {})
                snapshot = XIntelPostSnapshot(
                    scan_id=scan_id,
                    account_id=body.account_id,
                    benchmark_id=benchmark.id,
                    tweet_id=tweet_id,
                    tweet_url=str(post.get("url") or ""),
                    author_handle=str(
                        author.get("handle") or benchmark.handle),
                    author_name=str(
                        author.get("name") or benchmark.nickname),
                    author_verified=bool(
                        author.get("verified") or benchmark.verified),
                    author_followers=int(benchmark.follower_count or 0),
                    text=str(post.get("text") or ""),
                    posted_at=str(post.get("created_at") or ""),
                    view_count=metrics["views"],
                    like_count=metrics["likes"],
                    reply_count=metrics["replies"],
                    retweet_count=metrics["retweets"],
                    engagement_rate=metrics["engagement_rate"],
                    exposure_efficiency=metrics["efficiency"],
                    radar_score=metrics["score"],
                    fetched_at=now,
                )
                session.add(snapshot)
                snapshots.append(snapshot)

        scan = session.get(XIntelScan, scan_id)
        scan.successful_accounts = successful
        scan.failed_accounts = failed
        scan.post_count = len(snapshots)
        scan.status = (
            "done" if successful == len(results)
            else "partial" if successful else "failed")
        scan.finished_at = now
        if failed:
            scan.error = f"{failed} 个对标账号读取失败"
        session.add(scan)
        session.commit()

        rows = session.exec(select(XIntelPostSnapshot).where(
            XIntelPostSnapshot.scan_id == scan_id
        ).order_by(
            XIntelPostSnapshot.radar_score.desc(),
            XIntelPostSnapshot.view_count.desc(),
        )).all()
        items = _intel_enriched_items(session, rows)
        cfg = load_x_intel_automation(body.account_id)
        candidates = explosion_candidates(
            items,
            min_views_per_hour=float(cfg["explosion_min_views_per_hour"]),
            min_view_delta=int(cfg["explosion_min_view_delta"]),
            min_efficiency=float(cfg["explosion_min_efficiency"]),
            min_engagement_rate=float(cfg["explosion_min_engagement_rate"]),
            limit=20,
        )
        new_alerts = persist_explosion_alerts(
            body.account_id, scan_id, candidates)
        return {
            "ok": successful > 0,
            "scan": _intel_scan_dict(scan),
            "items": items,
            "signals": candidates,
            "new_alerts": [alert_dict(row) for row in new_alerts],
        }


class XGrowthCampaignIn(BaseModel):
    account_id: int
    target_count: int | None = Field(default=None, ge=1, le=10000)


def _growth_effective_limits(engine) -> dict:
    del engine
    return {
        "target_interval_seconds": 60,
        "interval_min_seconds": 50,
        "interval_max_seconds": 70,
        "cooldown_seconds": 900,
        "note": (
            "一键浇友实际按每位50-70秒随机节奏执行；"
            "不再叠加旧SOCIAL小时/每日额度。仍保留账号串行、"
            "活跃时段、平台硬熔断、真实限流冷却与uncertain防重复。"
        ),
    }


@router.get("/growth-campaign")
async def growth_campaign_status(account_id: int):
    _browser, engine = _runtime()
    with get_session() as session:
        account = session.get(DouyinAccount, account_id)
        if not account or account.platform != "x":
            raise HTTPException(400, "请选择有效的 X 账号")
    state = load_growth_campaign(account_id)
    with get_session() as session:
        rows = session.exec(select(AccountActionTask).where(
            AccountActionTask.platform == "x",
            AccountActionTask.account_id == account_id,
            AccountActionTask.action == "follow",
            AccountActionTask.status.in_(["pending", "doing", "uncertain"]),
        )).all()
        active = [
            {
                "id": row.id,
                "status": row.status,
                "handle": row.target_uid,
                "nickname": row.target_nick,
            }
            for row in rows if parse_growth_task_metadata(row.content)
        ]
    return {
        "ok": True,
        "state": state,
        "active_tasks": active,
        "limits": _growth_effective_limits(engine),
    }


@router.post("/growth-campaign/start")
async def growth_campaign_start(body: XGrowthCampaignIn):
    browser, engine = _runtime()
    with get_session() as session:
        account = session.get(DouyinAccount, body.account_id)
        if not account or account.platform != "x":
            raise HTTPException(400, "请选择有效的 X 账号")
        if account.status == "invalid" or not account.storage_state:
            raise HTTPException(400, "X登录态失效，请在面板手动登录后重试")
        session.expunge(account)

    decision = engine.risk.preflight(body.account_id, OperationKind.READ_LIGHT)
    if not decision.allowed:
        raise HTTPException(429, f"当前 X 账号暂不可读取：{decision.reason}")
    identity = browser.identity_for(account)
    try:
        async with engine.operation_guard(
                body.account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-growth-login-check:{body.account_id}"):
            await fetch_x_self_profile(browser, identity)
        engine.risk.record_success(body.account_id, OperationKind.READ_LIGHT)
    except Exception as exc:
        text = str(exc)
        if "logged_out:" in text:
            raise HTTPException(
                400, "X登录态失效，请在面板手动登录后重试") from exc
        engine.risk.record_failure(body.account_id, OperationKind.READ_LIGHT, exc)
        raise HTTPException(400, f"X登录态校验失败：{text}") from exc

    target_count = (
        save_x_ops_target_count(body.account_id, body.target_count)
        if body.target_count is not None
        else get_x_ops_target_count(body.account_id)
    )
    state = start_growth_campaign(
        body.account_id, interval_seconds=60, cooldown_seconds=900,
        target_count=target_count)
    return {
        "ok": True,
        "state": state,
        "limits": _growth_effective_limits(engine),
    }


@router.post("/growth-campaign/stop")
async def growth_campaign_stop(body: XGrowthCampaignIn):
    _browser, engine = _runtime()
    with get_session() as session:
        account = session.get(DouyinAccount, body.account_id)
        if not account or account.platform != "x":
            raise HTTPException(400, "请选择有效的 X 账号")
        rows = session.exec(select(AccountActionTask).where(
            AccountActionTask.platform == "x",
            AccountActionTask.account_id == body.account_id,
            AccountActionTask.action == "follow",
            AccountActionTask.status == "pending",
        )).all()
        canceled = 0
        for row in rows:
            if not parse_growth_task_metadata(row.content):
                continue
            before = row.status
            row.status = "canceled"
            row.scheduled_at = None
            row.error = "一键浇友已停止，取消尚未执行的关注任务"
            session.add(row)
            add_task_event(
                session, queue_type="actions", row_id=row.id,
                event_type="campaign:canceled",
                from_status=before, to_status="canceled",
                actor="x_growth",
                detail="用户停止一键浇友，取消尚未执行的关注任务",
            )
            canceled += 1
        session.commit()
    state = stop_growth_campaign(body.account_id)
    return {
        "ok": True,
        "state": state,
        "canceled_pending": canceled,
        "limits": _growth_effective_limits(engine),
    }


class XRelationshipIn(BaseModel):
    account_id: int
    handle: str = Field(min_length=1, max_length=100)
    action: Literal["follow", "unfollow"]


@router.post("/relationship")
async def relationship(body: XRelationshipIn):
    _browser, engine = _runtime()
    _x_account(body.account_id)
    try:
        task = create_x_relationship_task(
            body.account_id, body.handle, body.action)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if task["status"] == "uncertain":
        return {"ok": False, "uncertain": True, **task}
    try:
        result = await perform_queue_action(
            "actions", task["task_id"], "run-now", engine=engine)
    except QueueActionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"ok": True, "queued_via": "actions", **task, "execution": result}
