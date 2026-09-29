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
        if "互关" in text or "诚信" in text or "浇好朋友" in text or "浇朋友" in text:
            options = [
                "诚信互暖，一起把号做起来🤝",
                "必须支持，同行路上一起并肩作战🔥",
                "已阅已支持，常来串门呀！🤝",
            ]
            return random.choice(options)
        return self.engine.generate_micro_reply(tweet_text, author_name)

    def record_success(self, author_nick: str, author_handle: str, tweet_link: str, tweet_text: str, reply_text: str):
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        self.progress["completed_count"] = self.progress.get("completed_count", 0) + 1

        if "replied_links" not in self.progress:
            self.progress["replied_links"] = {}
        self.progress["replied_links"][tweet_link] = {
            "time": now_str,
            "author_nick": author_nick,
            "author_handle": author_handle,
            "tweet_text": tweet_text[:60],
            "reply_text": reply_text,
        }

        if "replied_authors" not in self.progress:
            self.progress["replied_authors"] = {}
        self.progress["replied_authors"][author_handle] = self.progress["replied_authors"].get(author_handle, 0) + 1

        self._save_progress()

        try:
            ok = self.feishu.record_reply(
                target_nick=author_nick,
                target_handle=author_handle,
                reply_text=reply_text,
                tweet_link=tweet_link,
                actions=["留言"],
                refollow_status="—",
                note=f"100条挑战 [第{self.progress['completed_count']}条]",
            )
            print(f"[Feishu] Synced record #{self.progress['completed_count']} -> {author_handle}: {ok}")
        except Exception as e:
            print(f"[Feishu] Sync error for #{self.progress['completed_count']}:", e)
