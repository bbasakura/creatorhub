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
    normalize_tweet_ref,
    reply_x,
)
from ..platforms.x.relationship import normalize_x_handle, set_x_following
from ..risk import OperationKind

router = APIRouter(prefix="/api/x", tags=["x"])


def _runtime():
    from .. import main as main_app
    if main_app.browser is None:
        raise HTTPException(503, "浏览器未就绪")
    if main_app.engine is None:
        raise HTTPException(503, "引擎未就绪")
    return main_app.browser, main_app.engine


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
        async with engine.operation_guard(
                account_id, OperationKind.READ_LIGHT,
                fallback_key=f"x-timeline:{account_id}"):
            items = await fetch_x_following_timeline(browser, identity, limit=limit)
        engine.risk.record_success(account_id, OperationKind.READ_LIGHT)
        return {"ok": True, "items": items, "count": len(items)}
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


class XReplyIn(BaseModel):
    account_id: int
    tweet_ref: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=280)
    author_handle: str = Field(default="", max_length=32)


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
