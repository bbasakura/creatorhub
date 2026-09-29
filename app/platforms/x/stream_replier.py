"""X (Twitter) 为你推荐流自动化回复与调度模块.

严格遵守准则:
1. 坚决杜绝任何虚假客套话（严禁“已关注/已订阅/已支持/互关互暖/常来串门”等虚假套话）。
2. 针对博主帖子的具体语义、问题、痛点，表达真实的个人见解与看法。
3. 短时间内评论过的博主坚决不再评论 (max_daily=1)。
4. 严格去重已回复推文。
"""

import asyncio
import os
import sys
import json
import time
from typing import Dict, Any, List, Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.platforms.x.batch_replier import XBatchReplier
from app.platforms.x.reply_decision import decide_reply
from app.platforms.x.xbangdan_crawler import XBangDanCrawler


class XStreamReplier:
    def __init__(
        self,
        own_handle: str = "",
        xbangdan_crawler: Optional[XBangDanCrawler] = None,
    ):
        self.batch_replier = XBatchReplier()
        self.own_handle = str(own_handle or "").strip().lstrip("@").casefold()
        self.xbangdan = xbangdan_crawler or XBangDanCrawler()
        try:
            self.target_handles = {
                h.lstrip("@").casefold() for h in self.xbangdan.get_target_handles(50)
            }
        except Exception:
            self.target_handles = set()

    @staticmethod
    def _ai_config() -> Dict[str, Any]:
        try:
            from app.settings import get_setting
            if get_setting("ai_enabled", "0") != "1":
                return {}
            return {
                "base_url": get_setting("ai_base_url", ""),
                "api_key": get_setting("ai_api_key", ""),
                "model": get_setting("ai_model", ""),
                "temperature": get_setting("ai_temperature", "0.35"),
                "timeout": 20,
            }
        except Exception:
            return {}

    def filter_raw_tweets(self, raw_tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤推文，确保未回复过、作者未在短时间内回复过、非自身账号."""
        valid_candidates = []
        seen_handles = set()

        for item in raw_tweets:
            link = item.get("tweetLink", "")
            handle = item.get("authorHandle", "")
            nick = item.get("authorNick", "")
            text = item.get("tweetText", "")

            if not link or not link.startswith("https://x.com/"):
                continue

            # 过滤自己；账号 handle 由调用方注入，不在通用模块硬编码具体账号。
            if self.own_handle and handle.lstrip("@").casefold() == self.own_handle:
                continue

            # 过滤本批次内重复 handle
            if handle.lower() in seen_handles:
                continue

            # 过滤已回复推文
            if self.batch_replier.is_link_replied(link):
                continue

            # 严格限制：短时间内评论过的博主坚决不再评论 (max_daily=1)
            if not self.batch_replier.can_reply_author(handle, max_daily=1):
                continue

            seen_handles.add(handle.lower())
            is_target = handle.lstrip("@").casefold() in self.target_handles
            valid_candidates.append({
                "tweetLink": link,
                "authorHandle": handle,
                "authorNick": nick,
                "tweetText": text,
                "isTargetCreator": is_target,
            })

        # 优先将 X 榜单上榜的黑马与高增长创作者排在处理队列最前面
        valid_candidates.sort(key=lambda c: 0 if c.get("isTargetCreator") else 1)
        return valid_candidates

    def get_target_creator_handles(self) -> List[str]:
        """获取 X 榜单收录的靶向目标博主 Handle 列表."""
        return list(self.xbangdan.get_target_handles(50))

    async def prepare_candidates(self, raw_tweets: List[Dict[str, Any]], *,
                                 threshold: int = 6, limit: int = 20,
                                 ai: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Score candidates and generate replies without writing to X."""
        prepared: List[Dict[str, Any]] = []
        config = self._ai_config() if ai is None else dict(ai)
        for item in self.filter_raw_tweets(raw_tweets):
            decision = await decide_reply(
                item.get("tweetText", ""),
                author_handle=item.get("authorHandle", ""),
                ai=config, threshold=threshold)
            if not decision.eligible or not decision.reply:
                continue
            prepared.append({
                **item,
                "replyText": decision.reply,
                "decisionScore": decision.score,
                "decisionReason": decision.reason,
                "decisionSource": decision.source,
            })
            if len(prepared) >= max(1, min(50, int(limit or 20))):
                break
        return prepared

    def enqueue_prepared_drafts(self, account_id: int,
                                prepared: List[Dict[str, Any]], *,
                                limit: int = 20) -> List[Dict[str, Any]]:
        """Persist reply drafts only; the CreatorHub worker remains the sole writer."""
        queued: List[Dict[str, Any]] = []
        for item in prepared[:max(1, min(50, int(limit or 20)))]:
            queued.append(self.batch_replier.enqueue_reply_draft(
                account_id=account_id,
                author_nick=item.get("authorNick", ""),
                author_handle=item.get("authorHandle", ""),
                tweet_link=item.get("tweetLink", ""),
                tweet_text=item.get("tweetText", ""),
                reply_text=item.get("replyText", ""),
            ))
        return queued

    def record_one(self, author_nick: str, author_handle: str, tweet_link: str, tweet_text: str, reply_text: str) -> int:
        """记录单条成功并同步飞书."""
        self.batch_replier.record_success(
            author_nick=author_nick,
            author_handle=author_handle,
            tweet_link=tweet_link,
            tweet_text=tweet_text,
            reply_text=reply_text,
        )
        return self.batch_replier.progress.get("completed_count", 0)

    @staticmethod
    def filter_file_candidates(input_path: str, output_path: str):
        sr = XStreamReplier()
        with open(input_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        filtered = sr.filter_raw_tweets(raw)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)
        print(f"Filtered {len(filtered)} clean candidates.")

    @staticmethod
    def prepare_file_candidates(input_path: str, output_path: str,
                                threshold: int = 6, limit: int = 20):
        sr = XStreamReplier()
        with open(input_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        prepared = asyncio.run(sr.prepare_candidates(
            raw, threshold=threshold, limit=limit))
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(prepared, f, ensure_ascii=False, indent=2)
        print(f"Prepared {len(prepared)} reply drafts; nothing was sent to X.")

    @staticmethod
    def enqueue_file_drafts(account_id: int, input_path: str,
                            output_path: str = "") -> List[Dict[str, Any]]:
        sr = XStreamReplier()
        with open(input_path, "r", encoding="utf-8") as f:
            prepared = json.load(f)
        queued = sr.enqueue_prepared_drafts(account_id, prepared)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(queued, f, ensure_ascii=False, indent=2)
        print(f"Queued {len(queued)} durable CommentTask drafts; nothing was sent to X.")
        return queued

    @staticmethod
    def process_record_file(record_path: str) -> int:
        sr = XStreamReplier()
        with open(record_path, "r", encoding="utf-8") as f:
            rec = json.load(f)
        cnt = sr.record_one(
            author_nick=rec.get("authorNick", ""),
            author_handle=rec.get("authorHandle", ""),
            tweet_link=rec.get("tweetLink", ""),
            tweet_text=rec.get("tweetText", ""),
            reply_text=rec.get("replyText", ""),
        )
        return cnt

    def get_progress(self) -> Dict[str, Any]:
        return {
            "completed": self.batch_replier.progress.get("completed_count", 0),
            "target": self.batch_replier.progress.get("target", 202),
        }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "filter" and len(sys.argv) >= 4:
            XStreamReplier.filter_file_candidates(sys.argv[2], sys.argv[3])
            sys.exit(0)
        elif cmd == "prepare" and len(sys.argv) >= 4:
            XStreamReplier.prepare_file_candidates(sys.argv[2], sys.argv[3])
            sys.exit(0)
        elif cmd == "enqueue-drafts" and len(sys.argv) >= 4:
            output = sys.argv[4] if len(sys.argv) >= 5 else ""
            XStreamReplier.enqueue_file_drafts(int(sys.argv[2]), sys.argv[3], output)
            sys.exit(0)
        elif cmd == "record" and len(sys.argv) >= 3:
            cnt = XStreamReplier.process_record_file(sys.argv[2])
            print("Current count:", cnt)
            sys.exit(0)
    sr = XStreamReplier()
    print("Stream Replier Progress:", sr.get_progress())
