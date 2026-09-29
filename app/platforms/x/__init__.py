"""X (Twitter) platform adapter for CreatorHub.

核心浏览器能力必须可独立启动；题材采集/生成扩展按需懒加载，避免其开发中状态
阻断 CreatorHub 的登录、时间线、发布、回复与关注链路。
"""
from __future__ import annotations

from importlib import import_module

_CORE_EXPORTS = []
try:
    from .client import (
        XWriteOutcome,
        compose_x_text,
        fetch_x_following_timeline,
        fetch_x_self_profile,
        fetch_x_my_works,
        fetch_x_relationships,
        fetch_x_dm_conversations,
        fetch_x_dm_history,
        interactive_x_login,
        normalize_tweet_ref,
        publish_x,
        reply_x,
    )
    _CORE_EXPORTS.extend([
        "XWriteOutcome",
        "compose_x_text",
        "fetch_x_following_timeline",
        "fetch_x_self_profile",
        "fetch_x_my_works",
        "fetch_x_relationships",
        "fetch_x_dm_conversations",
        "fetch_x_dm_history",
        "interactive_x_login",
        "normalize_tweet_ref",
        "publish_x",
        "reply_x",
    ])
except Exception:
    pass

try:
    from .relationship import (
        XRelationshipOutcome,
        normalize_x_handle,
        set_x_following,
    )
    _CORE_EXPORTS.extend([
        "XRelationshipOutcome",
        "normalize_x_handle",
        "set_x_following",
    ])
except Exception:
    pass
_TOPIC_EXPORTS = {
    "XPostingEngine": (".posting_engine", "XPostingEngine"),
    "XReplyEngine": (".reply_engine", "XReplyEngine"),
    "XBatchReplier": (".batch_replier", "XBatchReplier"),
    "XFeishuSync": (".feishu_sync", "XFeishuSync"),
    "TopHubCrawler": (".tophub_crawler", "TopHubCrawler"),
}


def __getattr__(name: str):
    target = _TOPIC_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = [*_CORE_EXPORTS, *_TOPIC_EXPORTS]
