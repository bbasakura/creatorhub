"""X (Twitter) 未回关博主核验、最新帖求回关与24小时观察管理模块."""

import os
import sys
import json
import time
import random
from typing import Dict, Any, List, Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.platforms.x.feishu_sync import XFeishuSync

TRACKER_FILE = os.path.expandvars(r"%TEMP%\x_refollow_tracker.json")
PROGRESS_FILE = os.path.expandvars(r"%TEMP%\x_unreciprocated_pipeline.json")

REMIND_PHRASES = [
    "大佬顺手回个关🤝，一起交流交流～",
    "已关注大佬，求翻牌回个关呀🔥",
    "大佬求个回关，同频路上一起搞起👍",
    "前排支持大佬，顺便蹲个回关🤝",
    "同频好友来串门啦，大佬记得回个关呀☕️",
    "关注大佬好几天了，顺手回个关并肩作战呀🔥",
]


import re

VALID_HANDLE_PATTERN = re.compile(r'^[A-Za-z0-9_]{1,15}$')


class UnreciprocatedManager:
    def __init__(self, tracker_file: str = TRACKER_FILE, progress_file: str = PROGRESS_FILE):
        self.tracker_file = tracker_file
        self.progress_file = progress_file
        self.feishu = XFeishuSync()
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # 从 tracker_file 初始化
        targets = {}
        if os.path.exists(self.tracker_file):
            try:
                with open(self.tracker_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    targets = data.get("targets", {})
            except Exception:
                pass

        return {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(targets),
            "checked_refollowed": 0,
            "reminded_count": 0,
            "failed_count": 0,
            "rate_limited_until": 0,
            "targets": targets,
        }

    def is_rate_limited(self) -> bool:
        return time.time() < self.state.get("rate_limited_until", 0)

    def trigger_rate_limit(self, minutes: int = 15):
        self.state["rate_limited_until"] = time.time() + minutes * 60
        self.save_state()
        print(f"[RateLimit] Triggered rate limit cooldown for {minutes} minutes.")

    def save_state(self):
        try:
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Failed to save pipeline state:", e)

    def get_pending_targets(self, limit: int = 5, include_confirmed: bool = True) -> List[Dict[str, Any]]:
        """获取尚未核验或处理的候选博主."""
        pending = []
        for handle, info in self.state.get("targets", {}).items():
            clean = info.get("clean_handle", "")
            if not VALID_HANDLE_PATTERN.match(clean):
                continue
            st = info.get("status")
            refollow = info.get("refollow")
            if refollow in ["已回关", "是"] or st in ["already_refollowed", "reminded_waiting_24h", "skipped_no_tweets", "not_following"]:
                continue
            # 如果不包含 confirmed_unreciprocated（纯筛查阶段只找纯 pending）
            if not include_confirmed and st == "confirmed_unreciprocated":
                continue
            pending.append(info)
            if len(pending) >= limit:
                break
        return pending

    def get_confirmed_unreciprocated_targets(self, limit: int | None = 5) -> List[Dict[str, Any]]:
        """专门获取已确认未回关且待催关的博主."""
        targets = []
        for handle, info in self.state.get("targets", {}).items():
            clean = info.get("clean_handle", "")
            if not VALID_HANDLE_PATTERN.match(clean):
                continue
            st = info.get("status")
            if st == "confirmed_unreciprocated":
                targets.append(info)
                if limit is not None and len(targets) >= limit:
                    break
        return targets

    def get_dynamic_step_targets(self, interval_min: int = 5, end_hour: int = 24) -> List[Dict[str, Any]]:
        """根据当前系统时间动态计算距离今晚24点每次触发所需的批次数量，确保在24点前均匀完成."""
        now = time.localtime()
        current_minutes = now.tm_hour * 60 + now.tm_min
        target_minutes = end_hour * 60 - 5  # 23:55 前完成
        remaining_minutes = max(5, target_minutes - current_minutes)
        remaining_cycles = max(1, remaining_minutes // interval_min)

        all_confirmed = self.get_confirmed_unreciprocated_targets(limit=1000)
        remaining_count = len(all_confirmed)

        if remaining_count == 0:
            return []

        # 向上取整均匀分配，单次上限为 4（保证单次执行时间在 75~85s 内，杜绝超时）
        calculated_limit = max(1, min(4, (remaining_count + remaining_cycles - 1) // remaining_cycles))
        print(f"[Dynamic Pacing] Remaining targets: {remaining_count}, Remaining minutes: {remaining_minutes}, "
              f"Remaining cycles: {remaining_cycles}, Calculated batch size: {calculated_limit}", file=sys.stderr)
        return all_confirmed[:calculated_limit]

    def mark_refollowed(self, clean_handle: str, nick: str = ""):
        """标记该博主已回关，跳过处理."""
        if clean_handle in self.state["targets"]:
            self.state["targets"][clean_handle]["status"] = "already_refollowed"
            self.state["targets"][clean_handle]["refollow"] = "已回关"
            self.state["targets"][clean_handle]["verified_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.state["checked_refollowed"] = self.state.get("checked_refollowed", 0) + 1
        self.save_state()
        print(f"[Verified] @{clean_handle} already follows you. Skipped.")

    def mark_not_following(self, clean_handle: str):
        """标记我们没有关注该博主."""
        if clean_handle in self.state["targets"]:
            self.state["targets"][clean_handle]["status"] = "not_following"
            self.state["targets"][clean_handle]["verified_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_state()
        print(f"[Notice] We are not following @{clean_handle}. Skipped.")

    def mark_confirmed_unreciprocated(self, clean_handle: str):
        """标记确认未回关，待留言催关."""
        if clean_handle in self.state["targets"]:
            self.state["targets"][clean_handle]["status"] = "confirmed_unreciprocated"
            self.state["targets"][clean_handle]["verified_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_state()
        print(f"[Confirmed] @{clean_handle} does NOT follow you. Ready for reminder.")

    def mark_no_tweets(self, clean_handle: str):
        self.mark_skipped_no_tweets(clean_handle)

    def mark_skipped_no_tweets(self, clean_handle: str):
        """标记该博主没有推文或不可回复."""
        if clean_handle in self.state["targets"]:
            self.state["targets"][clean_handle]["status"] = "skipped_no_tweets"
            self.state["targets"][clean_handle]["verified_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_state()
        print(f"[Skip] @{clean_handle} has no tweets to reply. Skipped.")

    def record_reminded(self, clean_handle: str, nick: str, tweet_link: str, reply_text: str):
        """记录已在其最新推文留言求回关，开启24小时倒计时."""
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        if clean_handle in self.state["targets"]:
            self.state["targets"][clean_handle]["status"] = "reminded_waiting_24h"
            self.state["targets"][clean_handle]["remind_time"] = now_str
            self.state["targets"][clean_handle]["remind_tweet"] = tweet_link
            self.state["targets"][clean_handle]["remind_text"] = reply_text
            self.state["targets"][clean_handle]["refollow"] = "未回关_已催"

        self.state["reminded_count"] = self.state.get("reminded_count", 0) + 1
        self.save_state()

        # 飞书同步
        try:
            ok = self.feishu.record_reply(
                target_nick=nick or clean_handle,
                target_handle=f"@{clean_handle}",
                reply_text=reply_text,
                tweet_link=tweet_link,
                actions=["留言"],
                refollow_status="未回关",
                note=f"24小时观察 [第{self.state['reminded_count']}位求回关催促]",
            )
            print(f"[Feishu] Synced reminder #{self.state['reminded_count']} -> @{clean_handle}: {ok}")
        except Exception as e:
            print(f"[Feishu] Sync reminder error for @{clean_handle}:", e)

    def get_summary(self) -> Dict[str, Any]:
        targets = self.state.get("targets", {})
        counts = {}
        for v in targets.values():
            st = v.get("status", "pending")
            counts[st] = counts.get(st, 0) + 1
        return {
            "total_targets": len(targets),
            "status_distribution": counts,
            "reminded_waiting_24h": self.state.get("reminded_count", 0),
            "checked_refollowed": self.state.get("checked_refollowed", 0),
        }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        mgr = UnreciprocatedManager()
        if cmd == "get":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            targets = mgr.get_pending_targets(limit)
            print(json.dumps(targets, ensure_ascii=False))
            sys.exit(0)
        elif cmd == "get_pure_pending":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            targets = mgr.get_pending_targets(limit, include_confirmed=False)
            print(json.dumps(targets, ensure_ascii=False))
            sys.exit(0)
        elif cmd == "get_confirmed":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            targets = mgr.get_confirmed_unreciprocated_targets(limit)
            print(json.dumps(targets, ensure_ascii=False))
            sys.exit(0)
        elif cmd == "get_dynamic":
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            end_h = int(sys.argv[3]) if len(sys.argv) > 3 else 24
            targets = mgr.get_dynamic_step_targets(interval, end_h)
            print(json.dumps(targets, ensure_ascii=False))
            sys.exit(0)
        elif cmd == "mark_refollowed" and len(sys.argv) >= 3:
            handle = sys.argv[2]
            nick = sys.argv[3] if len(sys.argv) > 3 else ""
            mgr.mark_refollowed(handle, nick)
            sys.exit(0)
        elif cmd == "mark_not_following" and len(sys.argv) >= 3:
            handle = sys.argv[2]
            mgr.mark_not_following(handle)
            sys.exit(0)
        elif cmd == "mark_no_tweets" and len(sys.argv) >= 3:
            handle = sys.argv[2]
            mgr.mark_no_tweets(handle)
            sys.exit(0)
        elif cmd == "mark_unreciprocated" and len(sys.argv) >= 3:
            handle = sys.argv[2]
            mgr.mark_confirmed_unreciprocated(handle)
            sys.exit(0)
        elif cmd == "record" and len(sys.argv) >= 3:
            rec_file = sys.argv[2]
            with open(rec_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            mgr.record_reminded(d["clean_handle"], d["nick"], d["tweet_link"], d["reply_text"])
            sys.exit(0)
        elif cmd == "summary":
            print(json.dumps(mgr.get_summary(), ensure_ascii=False))
            sys.exit(0)

    mgr = UnreciprocatedManager()
    print("Summary:", mgr.get_summary())
    pending = mgr.get_pending_targets(5)
    print("Pending sample count:", len(pending))
    for p in pending:
        print(f" - @{p['clean_handle']} ({p.get('nick', '')})")
