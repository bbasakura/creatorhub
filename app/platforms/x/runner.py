"""X (Twitter) 自动化主控调度器 (X Runner).

集成:
1. XPostingEngine: 自动生成与安全校验高质量原创短推
2. XReplyEngine: 自动识别推文意图生成 4~15 字极短口水式真人回复
3. XBrowserOps: 浏览器端 DataTransfer paste 无痕输入与回读校验
4. XFeishuSync: 同步落库飞书多维表格（台账 App: FCLabM00oaErGAsXJ00cjkNjnJD, Table: tblIj4aDV3hO2A0x）
"""

import time
import random
import os
import sys

# 保证根目录在 sys.path 中
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from typing import Dict, Any, List, Optional
from app.platforms.x.posting_engine import XPostingEngine
from app.platforms.x.reply_engine import XReplyEngine
from app.platforms.x.browser_ops import XBrowserOps
from app.platforms.x.feishu_sync import XFeishuSync


class XRunner:
    """X 平台自动化主控运行器"""

    def __init__(self):
        self.poster = XPostingEngine()
        self.replier = XReplyEngine()
        self.browser_ops = XBrowserOps()
        self.feishu = XFeishuSync()

    def plan_next_post(self, category: Optional[str] = None) -> Dict[str, Any]:
        """规划下一条要发布的推文，并完成格式质检"""
        text = self.poster.generate_post(category)
        val = self.poster.validate_post(text)
        return {
            "text": text,
            "category": category or "general",
            "is_valid": val["valid"],
            "reason": val["reason"],
            "inject_code": self.browser_ops.get_post_workflow_code(text),
        }

    def on_post_success(self, post_text: str, post_link: str = "", category: str = "", note: str = ""):
        """主帖发布成功后的钩子: 同步飞书多维表格"""
        ok = self.feishu.record_post(
            post_text=post_text,
            post_link=post_link,
            category=category,
            note=note or "自动化引擎发布",
        )
        print(f"[Feishu] Post record synced: {ok}")
        return ok

    def plan_reply(self, tweet_text: str, author_nick: str = "", author_handle: str = "", tweet_link: str = "") -> Dict[str, Any]:
        """针对指定推文规划微回复内容与浏览器执行代码"""
        intent = self.replier.classify_intent(tweet_text)
        reply_text = self.replier.generate_micro_reply(tweet_text, author_nick)
        return {
            "tweet_text": tweet_text,
            "author_nick": author_nick,
            "author_handle": author_handle,
            "intent": intent,
            "reply_text": reply_text,
            "tweet_link": tweet_link,
            "inject_code": self.browser_ops.get_reply_workflow_code("", reply_text),
        }

    def on_reply_success(
        self,
        target_nick: str,
        target_handle: str,
        reply_text: str,
        tweet_link: str = "",
        refollow_status: str = "—",
        note: str = "",
    ):
        """回复成功后的钩子: 记录内存历史并同步飞书多维表格"""
        self.replier.record_reply(tweet_link, target_handle)
        ok = self.feishu.record_reply(
            target_nick=target_nick,
            target_handle=target_handle,
            reply_text=reply_text,
            tweet_link=tweet_link,
            actions=["留言"],
            refollow_status=refollow_status,
            note=note or "极速微回复",
        )
        print(f"[Feishu] Reply record synced: {ok}")
        return ok


if __name__ == "__main__":
    runner = XRunner()
    post_plan = runner.plan_next_post("pain_point")
    print("=== Planned Post ===")
    print(post_plan["text"])
    print(f"Valid: {post_plan['is_valid']}")

    print("\n=== Planned Reply Sample ===")
    reply_plan = runner.plan_reply(
        tweet_text="大家觉得现在做个人IP还来得及吗？",
        author_nick="Web3探索者",
        author_handle="@web3_explorer",
        tweet_link="https://x.com/web3_explorer/status/123456789",
    )
    print(f"Author: {reply_plan['author_nick']} ({reply_plan['author_handle']})")
    print(f"Intent: {reply_plan['intent']} -> Reply: {reply_plan['reply_text']}")
