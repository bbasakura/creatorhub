"""X (Twitter) 批量自动化回帖执行器."""

import os
import sys
import json
import time
import random

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from typing import Dict, Any, List, Optional
from app.platforms.x.reply_engine import XReplyEngine
from app.platforms.x.feishu_sync import XFeishuSync

PROGRESS_FILE = os.path.expandvars(r"%TEMP%\x_reply_progress.json")


class XBatchReplier:
    def __init__(self, progress_file: str = PROGRESS_FILE):
        self.progress_file = progress_file
        self.engine = XReplyEngine()
        self.feishu = XFeishuSync()
        self.progress = self._load_progress()

    def _load_progress(self) -> Dict[str, Any]:
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "date": time.strftime("%Y-%m-%d"),
            "target": 100,
            "completed_count": 0,
            "replied_links": {},
            "replied_authors": {},
        }

    def _save_progress(self):
        try:
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(self.progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Failed to save progress:", e)

    def is_link_replied(self, link: str) -> bool:
        return link in self.progress.get("replied_links", {})

    def can_reply_author(self, author_handle: str, max_daily: int = 2) -> bool:
        count = self.progress.get("replied_authors", {}).get(author_handle, 0)
        return count < max_daily

    def generate_reply_for_tweet(self, tweet_text: str, author_name: str = "") -> str:
        text = tweet_text.lower()
        if "曝光" in text and ("500" in text or "50w" in text or "50万" in text or "怎么" in text or "如何" in text):
            options = [
                "多跟蓝V互评，多去大V评论区，曝光涨得飞快🔥",
                "恭喜达标！多跟同频好友互捧，曝光很快凑满🤝",
                "多发争议选择题，评论区互动起来曝光翻倍👍",
            ]
            return random.choice(options)
        if "碳水" in text or "早餐" in text or "月饼" in text:
            options = [
                "确实，高蛋白低碳水一整天都有精神👍",
                "哈哈同款早餐，搬砖人不容易☕️",
                "营养搭配到位，元气满满开工！🔥",
            ]
            return random.choice(options)
        if "团券" in text or "吃饭" in text or "买单" in text:
            options = [
                "必须用啊，能省一点是一点😂",
                "能团肯定团，没有团购都不想进店了",
                "绝不当大冤种，每次必搜优惠券👍",
            ]
            return random.choice(options)
        if "iphone" in text or "android" in text or "安卓" in text or "苹果" in text or "充值" in text:
            options = [
                "苹果有抽成，安卓往往便宜一些😂",
                "同问，苹果端确实普遍要贵一点",
                "安卓端好像便宜几块钱，苹果税太狠了",
            ]
            return random.choice(options)
        if "限制" in text or "风控" in text or "天塌了" in text or "封" in text:
            options = [
                "稳住心态，歇半小时再搞，别硬顶🔥",
                "太真实了，老马的算法日常搞人心态😂",
                "同病相怜，放慢点节奏就好了🤝",
            ]
            return random.choice(options)
        if "互关" in text or "诚信" in text or "浇好朋友" in text or "浇朋友" in text:
            options = [
                "诚信互暖，一起把号做起来🤝",
                "必须支持，同行路上一起并肩作战🔥",
                "已阅已支持，常来串门呀！🤝",
            ]
            return random.choice(options)
        return self.engine.generate_micro_reply(tweet_text, author_name)

    def enqueue_reply_draft(self, account_id: int, author_nick: str,
                            author_handle: str, tweet_link: str,
                            tweet_text: str, reply_text: str) -> Dict[str, Any]:
        """Create a durable CommentTask draft. This method never writes to X."""
        from app.services.x_workflow import create_x_reply_draft
        result = create_x_reply_draft(
            account_id, tweet_link, reply_text,
            author_handle=author_handle, source_text=tweet_text)
        result.update({
            "author_nick": author_nick,
            "author_handle": author_handle,
            "tweet_link": tweet_link,
            "reply_text": reply_text,
        })
        return result

    def record_success(self, author_nick: str, author_handle: str, tweet_link: str, tweet_text: str, reply_text: str):
        """Fail closed: only the durable CreatorHub worker may persist X success."""
        raise RuntimeError(
            "legacy X success stamping is disabled; "
            "wait for the durable CommentTask worker to confirm status=done"
        )
