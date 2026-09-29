import asyncio
from unittest.mock import AsyncMock, Mock, patch

from app.platforms.x.reply_decision import decide_reply, heuristic_score


def test_heuristic_filters_giveaway_and_rewards_substantive_question():
    low, reason = heuristic_score("关注抽奖，转发抽 10 个")
    high, _ = heuristic_score("这个 Agent 工作流为什么会在并发时重复执行？有没有更稳的架构方案？")
    assert low <= 1
    assert reason == "promotion_or_giveaway"
    assert high >= 7


def test_decision_falls_back_without_ai_config():
    result = asyncio.run(decide_reply(
        "这个自动化架构如何处理失败重试和幂等？",
        author_handle="tester", ai={}, threshold=6))
    assert result.source == "heuristic"
    assert result.eligible is True
    assert result.reply


def test_model_json_can_accept_high_value_reply():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": '{"score":8,"reason":"有技术讨论价值","reply":"关键是把提交边界和幂等键分开处理。"}'}}]
    }
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post.return_value = response
    with patch("app.platforms.x.reply_decision.httpx.AsyncClient", return_value=client):
        result = asyncio.run(decide_reply(
            "任务重试怎么避免重复发布？", author_handle="tester",
            ai={"base_url":"http://local","api_key":"k","model":"m"}, threshold=6))
    assert result.source == "model"
    assert result.score == 8
    assert result.eligible is True
    assert "提交边界" in result.reply


def test_model_prompt_includes_persona_and_interaction_memory():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": '{"score":8,"reason":"可继续讨论","reply":"这次可以从租约角度补一层。"}'}}]
    }
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post.return_value = response
    with patch("app.platforms.x.reply_decision.httpx.AsyncClient", return_value=client):
        result = asyncio.run(decide_reply(
            "任务领取还可能重复吗？", author_handle="tester",
            ai={"base_url":"http://local","api_key":"k","model":"m"},
            persona="偏工程实践，不说空话",
            interaction_context="之前讨论过提交边界，不要重复",
            threshold=6))
    body = client.post.call_args.kwargs["json"]
    prompt = body["messages"][1]["content"]
    assert "偏工程实践" in prompt
    assert "之前讨论过提交边界" in prompt
    assert result.eligible is True


def test_model_failure_returns_safe_fallback():
    with patch("app.platforms.x.reply_decision.httpx.AsyncClient", side_effect=RuntimeError("offline")):
        result = asyncio.run(decide_reply(
            "自动化任务失败应该怎么做幂等？",
            ai={"base_url":"http://local","api_key":"k","model":"m"}, threshold=6))
    assert result.source == "heuristic"
