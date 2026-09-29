"""X reply relevance and generation decision layer.

The decision service is side-effect free: it scores a candidate and produces a
suggested reply.  Actual writes remain in CreatorHub's guarded browser writer.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .reply_engine import XReplyEngine


_AD_OR_LOW_VALUE = (
    "抽奖", "转发抽", "关注抽", "加群", "私聊领取", "返现", "优惠券",
    "免费领取", "代购", "邀请码", "开户链接", "稳赚", "带单",
)
_VALUE_SIGNALS = (
    "为什么", "怎么", "如何", "区别", "原理", "架构", "数据", "实测",
    "经验", "复盘", "方案", "问题", "性能", "成本", "风险", "模型",
    "代码", "自动化", "ai", "agent", "大模型", "工作流",
)


@dataclass(frozen=True)
class ReplyDecision:
    eligible: bool
    score: int
    reason: str
    reply: str
    source: str

    def as_dict(self) -> dict:
        return asdict(self)


def heuristic_score(text: str) -> tuple[int, str]:
    value = str(text or "").strip()
    if not value:
        return 0, "empty"
    lowered = value.casefold()
    if any(token in lowered for token in _AD_OR_LOW_VALUE):
        return 1, "promotion_or_giveaway"
    if len(value) < 8:
        return 3, "too_short"
    score = 4
    if "?" in value or "？" in value:
        score += 2
    if any(token in lowered for token in _VALUE_SIGNALS):
        score += 2
    if len(value) >= 60:
        score += 1
    if value.count("http://") + value.count("https://") >= 2:
        score -= 2
    return max(0, min(10, score)), "heuristic"


def _fallback_decision(text: str, author_handle: str, threshold: int) -> ReplyDecision:
    score, reason = heuristic_score(text)
    eligible = score >= threshold
    reply = XReplyEngine().generate_micro_reply(text, author_handle) if eligible else ""
    return ReplyDecision(
        eligible=eligible, score=score, reason=reason,
        reply=reply, source="heuristic",
    )


def _extract_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            text = match.group(0)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("AI decision must be an object")
    return parsed


async def decide_reply(
        tweet_text: str, *, author_handle: str = "", ai: dict | None = None,
        threshold: int = 6, persona: str = "", interaction_context: str = "") -> ReplyDecision:
    threshold = max(1, min(10, int(threshold)))
    fallback = _fallback_decision(tweet_text, author_handle, threshold)
    cfg = dict(ai or {})
    base = str(cfg.get("base_url") or "").rstrip("/")
    key = str(cfg.get("api_key") or "")
    model = str(cfg.get("model") or "")
    if not (base and key and model):
        return fallback

    persona_text = str(persona or "").strip()[:1200]
    memory_text = str(interaction_context or "").strip()[:1800]
    context_parts = []
    if persona_text:
        context_parts.append(f"账号长期表达风格/立场：\n{persona_text}")
    if memory_text:
        context_parts.append(f"与该作者的历史互动：\n{memory_text}")
    extra_context = ("\n\n" + "\n\n".join(context_parts)) if context_parts else ""
    prompt = (
        "评估这条 X 帖子是否值得账号参与讨论，并生成一条简短、有信息量、不过度奉承的中文回复。\n"
        "返回严格 JSON：{\"score\":0到10整数,\"reason\":\"简短原因\","
        "\"reply\":\"1到2句回复\"}。广告、抽奖、诱导关注、纯无意义情绪帖应低分。\n"
        "不要声称做过未发生的动作；若有历史互动，避免重复同一句观点或装作第一次见面。\n"
        f"作者: @{author_handle}\n帖子: {str(tweet_text or '')[:1200]}{extra_context}"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是社交媒体讨论价值评估器，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(cfg.get("temperature") or 0.35),
        "max_tokens": 220,
    }
    try:
        async with httpx.AsyncClient(timeout=float(cfg.get("timeout") or 20)) as client:
            response = await client.post(
                base + "/chat/completions", json=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        response.raise_for_status()
        payload = response.json()
        content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        parsed = _extract_json(content)
        score = max(0, min(10, int(parsed.get("score", fallback.score))))
        reply = str(parsed.get("reply") or "").strip()[:180]
        reason = str(parsed.get("reason") or "model")[:240]
        eligible = score >= threshold and bool(reply)
        return ReplyDecision(
            eligible=eligible, score=score, reason=reason,
            reply=reply if eligible else "", source="model",
        )
    except Exception:
        return fallback
