"""X (Twitter) 自动化极速回帖引擎."""

import time
import random
from typing import Dict, Any, List, Optional

REPLY_LEXICON = {
    "question": [
        "好问题，我也在琢磨这个",
        "蹲一个行家的解答👇",
        "选A吧，容错率高一些",
        "果断选后者，搏一把！",
        "这得看兜里本金厚不厚了😂",
        "个人倾向第二个方案",
    ],
    "complaint": [
        "太真实了，简直人间真实",
        "同感，今天直接关电脑装死😂",
        "扎心了老铁，稳住",
        "确实，这破算法天天搞心态",
        "习惯就好，给老马打工是这样的",
        "抱团取暖，今天行情确实拉胯",
    ],
    "encouragement": [
        "牛的，一起加油冲！",
        "确实，熬过去就是另一片天",
        "向大佬看齐，默默学习🤝",
        "思路太清晰了，支持！",
        "搞起搞起，坚持就是胜利🔥",
        "必须顶你，同行路上一起卷！",
        "坐等大佬开更🔥",
        "期待期待，搞起搞起！",
    ],
    "daily": [
        "早啊，又是元气满满搬砖日☕️",
        "晚安，明天继续并肩作战🌙",
        "今日份打卡，已阅！",
        "哈哈哈绝了，今日最佳快乐源泉",
        "真实，这波我站你这边",
        "前排围观大佬日常",
        "搬砖人不容易，一起加油",
    ],
    "general": [
        "确实是这么个理",
        "赞同，切中要害了",
        "哈哈哈哈笑死我了",
        "说明你最近流量确实起来了🔥",
        "你够努力了，别太焦虑",
        "可以翻翻以前的总结，很有参考价值",
    ]
}


class XReplyEngine:
    """X 极速微回帖引擎"""

    def __init__(self, target_daily_replies: int = 100):
        self.target_daily_replies = target_daily_replies
        self.replied_tweet_ids = set()
        self.replied_users = {}

    def classify_intent(self, tweet_text: str) -> str:
        text = tweet_text.lower()
        if any(w in text for w in ["？", "?", "怎么选", "如何看待", "觉得呢", "大家呢", "求推荐", "有没有"]):
            return "question"
        if any(w in text for w in ["崩", "难", "累", "跌", "搞心态", "吐了", "离谱", "差", "完犊子"]):
            return "complaint"
        if any(w in text for w in ["搞定", "上线", "突破", "坚持", "思路", "心得", "总结", "干货", "分享", "跑通", "成了", "顺利", "肝", "更新", "发帖", "开搞"]):
            return "encouragement"
        if any(w in text for w in ["早", "晚安", "睡觉", "吃饭", "打卡", "开工", "周末", "忙", "搬砖", "日常"]):
            return "daily"
        return "general"

    def generate_micro_reply(self, tweet_text: str, author_name: str = "") -> str:
        intent = self.classify_intent(tweet_text)
        candidates = REPLY_LEXICON.get(intent, REPLY_LEXICON["general"])
        reply = random.choice(candidates)
        emojis = ["", "😂", "🤝", "🔥", "👍", "☕️", "👀"]
        chosen_emoji = random.choice(emojis)
        full_reply = f"{reply} {chosen_emoji}".strip()
        if len(full_reply) > 15:
            full_reply = full_reply[:15].strip()
        return full_reply

    def can_reply_user(self, user_handle: str, max_replies_per_user_daily: int = 3) -> bool:
        count = self.replied_users.get(user_handle, 0)
        return count < max_replies_per_user_daily

    def record_reply(self, tweet_id: str, user_handle: str):
        self.replied_tweet_ids.add(tweet_id)
        self.replied_users[user_handle] = self.replied_users.get(user_handle, 0) + 1
