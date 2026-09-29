"""CreatorHub X extension API.

Read and write operations are account-bound and reuse the existing engine gates.
The API intentionally exposes single-reply actions only; it does not run bulk
auto-reply loops.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_session
from ..models import DouyinAccount
from ..platforms.x.client import (
    fetch_x_following_timeline,
    fetch_x_search,
    normalize_tweet_ref,
    reply_x,
)
from ..platforms.x.relationship import normalize_x_handle, set_x_following
from ..risk import OperationKind
from ..services.runtime_context import get_runtime
from ..services.x_workflow import create_x_post_draft, create_x_reply_draft
from ..services.x_interaction_memory import load_x_interaction_memory
from ..platforms.x.providers import x_provider_status
from ..platforms.x.twikit_client import (
    TwikitAuthUnavailable, TwikitReadAdapter, TwikitUnavailable,
)
from ..platforms.x.reply_decision import decide_reply
from ..settings import get_setting
from ..platforms.x.twikit_compat import TwikitCompatibilityError


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
        provider = "twikit"
        fallback_reason = ""
        async with engine.operation_guard(
                body.account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-search:{body.account_id}:{body.query[:80]}"):
            try:
                items = await _twikit_adapter(body.account_id).search(
                    body.query, product=body.product, count=body.count)
            except Exception as provider_exc:
                if not _can_fallback_read(provider_exc):
                    raise
                fallback_reason = type(provider_exc).__name__
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
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
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
        provider = "browser"
        fallback_reason = ""
        async with engine.operation_guard(
                account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-timeline:{account_id}"):
            try:
                states = tuple(s for s in (
                    getattr(account, "storage_state", ""),
                    getattr(account, "creator_storage_state", ""),
                ) if s)
                items = await TwikitReadAdapter(
                    states, proxy=getattr(account, "proxy", ""),
                    user_agent=getattr(account, "ua", "")).timeline(count=limit)
                provider = "twikit"
            except Exception as provider_exc:
                if not _can_fallback_read(provider_exc):
                    raise
                fallback_reason = type(provider_exc).__name__
                items = await fetch_x_following_timeline(browser, identity, limit=limit)
        engine.risk.record_success(account_id, OperationKind.READ_LIGHT)
        payload = {"ok": True, "provider": provider, "items": items, "count": len(items)}
        if fallback_reason:
            payload["fallback_reason"] = fallback_reason
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
    browser, engine = _runtime()
    account = _x_account(body.account_id)
    try:
        tweet_id, canonical_url = normalize_tweet_ref(body.tweet_ref)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    decision = engine.risk.preflight(body.account_id, OperationKind.COMMENT)
    if not decision.allowed:
        raise HTTPException(429, decision.reason)
    identity = browser.identity_for(account)
    try:
        async with engine.operation_guard(
                body.account_id, OperationKind.COMMENT,
                fallback_key=f"x-reply:{body.account_id}:{tweet_id}"):
            ok, url, error = await reply_x(
                browser, identity, canonical_url, body.text)
    except Exception as exc:
        engine.risk.record_failure(body.account_id, OperationKind.COMMENT, exc)
        raise HTTPException(400, f"X 回复失败: {exc}") from exc
    if ok:
        engine.risk.record_success(body.account_id, OperationKind.COMMENT)
        return {"ok": True, "tweet_id": tweet_id, "url": url or canonical_url}
    if str(error or "").startswith("write_uncertain:"):
        return {"ok": False, "uncertain": True, "tweet_id": tweet_id,
                "url": canonical_url, "error": error}
    engine.risk.record_failure(body.account_id, OperationKind.COMMENT, error)
    raise HTTPException(400, error or "X 回复失败")


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


class XRelationshipIn(BaseModel):
    account_id: int
    handle: str = Field(min_length=1, max_length=100)
    action: Literal["follow", "unfollow"]


@router.post("/relationship")
async def relationship(body: XRelationshipIn):
    browser, engine = _runtime()
    account = _x_account(body.account_id)
    try:
        handle, profile_url = normalize_x_handle(body.handle)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    decision = engine.risk.preflight(body.account_id, OperationKind.SOCIAL)
    if not decision.allowed:
        raise HTTPException(429, decision.reason)

    identity = browser.identity_for(account)
    try:
        async with engine.operation_guard(
                body.account_id, OperationKind.SOCIAL,
                fallback_key=f"x-relationship:{body.account_id}:{body.action}:{handle.casefold()}"):
            outcome = await set_x_following(
                browser, identity, handle, body.action == "follow")
    except Exception as exc:
        engine.risk.record_failure(body.account_id, OperationKind.SOCIAL, exc)
        raise HTTPException(400, f"X 关注关系操作失败: {exc}") from exc

    if outcome.ok:
        if outcome.changed:
            engine.risk.record_success(body.account_id, OperationKind.SOCIAL)
        return {
            "ok": True,
            "action": body.action,
            "handle": handle,
            "url": profile_url,
            "changed": outcome.changed,
            "state": outcome.state,
        }

    if outcome.status == "uncertain":
        return {
            "ok": False,
            "uncertain": True,
            "action": body.action,
            "handle": handle,
            "url": profile_url,
            "changed": outcome.changed,
            "state": outcome.state,
            "error": outcome.error,
        }

    engine.risk.record_failure(
        body.account_id, OperationKind.SOCIAL, outcome.error or "X 关注关系操作失败")
    raise HTTPException(400, outcome.error or "X 关注关系操作失败")
