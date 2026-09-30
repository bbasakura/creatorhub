"""X (Twitter) 中文区数据榜单 (xbangdan.com) 爬取与题材解析模块.

数据源:
1. GitHub 开放镜像库: https://github.com/jedeeai/xbangdan (daily/ 归档快照)
2. 聚合 4 个维度冠军、涨粉榜 Top10、推文曝光榜 Top10 以及 24 小时最爆推文。
为 CreatorHub 提供：
- X 原生高互动爆款题材（供给 posting_engine）
- 靶向高增长/高权重博主名单（供给 stream_replier 优先互动队列）
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
RUNTIME_DIR = os.path.join(_PROJECT_ROOT, "runtime")
CACHE_FILE = os.path.join(RUNTIME_DIR, "xbangdan_cache.json")

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/jedeeai/xbangdan/main/daily"
GITHUB_API_CONTENTS = "https://api.github.com/repos/jedeeai/xbangdan/contents/daily"

FALLBACK_SNAPSHOT_MD = """# X榜单 · 2026-08-11

[https://xbangdan.com](https://xbangdan.com) 每天更新的 X 中文区数据榜单。
本页是统计日 2026-08-11 的存档，统计窗口是北京时间 08/11 08:00 – 08/12 08:00。

## 四个维度的冠军

| 维度 | 账号 | 数据 |
| --- | --- | --- |
| 发帖 | [空空道人](https://xbangdan.com/account/Kongkongda5882/) @Kongkongda5882 | 176 帖 |
| 评论 | [币圈屌老大](https://xbangdan.com/account/zhangshuai16888/) @zhangshuai16888 | 1581 条 |
| 涨粉 | [宝玉](https://xbangdan.com/account/dotey/) @dotey | +2824 粉 |
| 推文曝光 | [Theo](https://xbangdan.com/account/0xTheo520/) @0xTheo520 | 363.8 万 |

## 涨粉榜前十

| # | 账号 | 涨粉 | 总粉丝 |
| --- | --- | --- | --- |
| 1 | [宝玉](https://xbangdan.com/account/dotey/) @dotey | +2824 | 24.0 万 |
| 2 | [黄果短剧](https://xbangdan.com/account/huangguodrama/) @huangguodrama | +2774 | 36.8 万 |
| 3 | [歸藏(guizang.ai)](https://xbangdan.com/account/op7418/) @op7418 | +1867 | 16.7 万 |
| 4 | [Gorden Sun](https://xbangdan.com/account/Gorden_Sun/) @Gorden_Sun | +1845 | 6.4 万 |
| 5 | [小互](https://xbangdan.com/account/xiaohu/) @xiaohu | +1610 | 11.6 万 |
| 6 | [Orange AI](https://xbangdan.com/account/oran_ge/) @oran_ge | +1462 | 18.0 万 |
| 7 | [番茄大叔🇨🇳](https://xbangdan.com/account/uncleTomat0/) @uncleTomat0 | +1449 | 2.6 万 |
| 8 | [向阳乔木](https://xbangdan.com/account/vista8/) @vista8 | +1430 | 12.2 万 |
| 9 | [作家崔成浩](https://xbangdan.com/account/cuichenghao/) @cuichenghao | +1130 | 12.3 万 |
| 10 | [曾小道](https://xbangdan.com/account/Enzozhz/) @Enzozhz | +979 | 4011 |

## 推文曝光榜前十

| # | 账号 | 当日曝光 |
| --- | --- | --- |
| 1 | [Theo](https://xbangdan.com/account/0xTheo520/) @0xTheo520 | 363.8 万 |
| 2 | [颜克权](https://xbangdan.com/account/yantanzhang/) @yantanzhang | 333.6 万 |
| 3 | [王长富](https://xbangdan.com/account/wangchangfu88/) @wangchangfu88 | 326.7 万 |
| 4 | [动物园园长](https://xbangdan.com/account/weiyux2021/) @weiyux2021 | 324.0 万 |
| 5 | [Joruno](https://xbangdan.com/account/wsl8297/) @wsl8297 | 320.4 万 |
| 6 | [小宇妈妈](https://xbangdan.com/account/xiaoyumama9968/) @xiaoyumama9968 | 278.2 万 |
| 7 | [禿道道🐟](https://xbangdan.com/account/dearemon/) @dearemon | 251.8 万 |
| 8 | [JasonZ](https://xbangdan.com/account/Jason_WealthAI/) @Jason_WealthAI | 246.3 万 |
| 9 | [韩跑跑](https://xbangdan.com/account/HanPaoao/) @HanPaoao | 239.9 万 |
| 10 | [偏航](https://xbangdan.com/account/pianhangx/) @pianhangx | 185.1 万 |

## 24 小时最爆推文

1. **韩跑跑** （250.3 万 曝光）[看原帖](https://x.com/HanPaoao/status/2087482945594609814)
    > 卧槽，这是在干啥？？  内部视频流出来了？

2. **火山哥🕊️** （187.5 万 曝光）[看原帖](https://x.com/huoshan007/status/2087348135391825964)
    > 兄弟们，我昨晚手贱进了个“数据开盒”群，看完真给我干沉默了。  信息，名下地址、亲属关系、外卖收货点、社保、住院记录、酒店记录，甚至你常用哪个快递站都能串起来。…

3. **AB Kuai.Dong** （92.0 万 曝光）[看原帖](https://x.com/_FORAB/status/2087486229311046050)
    > X 平台让我觉得最厉害的地方在于  官方消息是今天 18 点公布的 但 X 上的多个消息源是昨天晚上  间隔差了 24 个小时

4. **李志 | Rational Investing** （89.2 万 曝光）[看原帖](https://x.com/LZRationalnvest/status/2087495753744928797)
    > 这个人信源从哪里来的，昨天就得知消息了？😂

5. **luolei** （56.6 万 曝光）[看原帖](https://x.com/luoleiorg/status/2087360992028377180)
    > 头疼，刚刚接到税务局电话，说核查到我 2024 年的境外收入还没申报，之前已经三次短信通知，没有处理，这次是电话联系警告。我有点奇怪，对面报了一个吓到我的数字，…
"""


class XBangDanCrawler:
    """X榜单 (xbangdan.com) 数据采集与解析器."""

    def __init__(self, cache_ttl_seconds: int = 1800, cache_file: str = CACHE_FILE):
        self.cache_ttl = cache_ttl_seconds
        self.cache_file = cache_file

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.cache_file):
            return None
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_time = data.get("_cached_at", 0)
            if time.time() - cached_time < self.cache_ttl:
                return data
        except Exception:
            pass
        return None

    def _save_cache(self, data: Dict[str, Any]):
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            data["_cached_at"] = time.time()
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[XBangDanCrawler] 写入缓存异常: {e}", file=sys.stderr)

    def _fetch_from_github_raw(self, date_str: str) -> Optional[str]:
        url = f"{GITHUB_RAW_BASE}/{date_str}.md"
        headers = {"User-Agent": "CreatorHub-XBangDan/1.0", "Accept": "text/plain"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8")
        except Exception:
            return None
        return None

    def _find_latest_github_file(self) -> Optional[str]:
        """通过 GitHub API 列出 daily/ 下的最新归档文件."""
        headers = {"User-Agent": "CreatorHub-XBangDan/1.0", "Accept": "application/json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(GITHUB_API_CONTENTS, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    files = json.loads(resp.read().decode("utf-8"))
                    md_files = [
                        f.get("name") for f in files
                        if isinstance(f, dict) and f.get("name", "").endswith(".md")
                    ]
                    if md_files:
                        md_files.sort(reverse=True)
                        latest_filename = md_files[0]
                        date_str = latest_filename[:-3]
                        return self._fetch_from_github_raw(date_str)
        except Exception:
            pass
        return None

    def fetch_markdown(self, target_date: Optional[str] = None) -> str:
        """获取指定日期或最新日期的 Markdown 文本."""
        if target_date:
            content = self._fetch_from_github_raw(target_date)
            if content:
                return content

        # 优先尝试今天与昨天
        now = datetime.now()
        for i in range(2):
            day_str = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            content = self._fetch_from_github_raw(day_str)
            if content:
                return content

        # 尝试已收录的历史日期快照
        historical = self._fetch_from_github_raw("2026-08-11")
        if historical:
            return historical

        # 尝试 GitHub API 列出的最新文件
        latest_content = self._find_latest_github_file()
        if latest_content:
            return latest_content

        return FALLBACK_SNAPSHOT_MD

    @staticmethod
    def parse_markdown(md_text: str) -> Dict[str, Any]:
        """解析 X榜单 Markdown 快照为结构化数据."""
        snapshot_date = ""
        date_match = re.search(r"#\s*X榜单\s*·\s*(\d{4}-\d{2}-\d{2})", md_text)
        if date_match:
            snapshot_date = date_match.group(1)

        champions: Dict[str, Dict[str, str]] = {}
        champ_section = re.search(
            r"##\s*四个维度的冠军\s*\n\s*\|[^\n]+\n\s*\|[^\n]+\n((?:\|[^\n]+\n?)+)",
            md_text,
        )
        if champ_section:
            for line in champ_section.group(1).strip().split("\n"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    dim = parts[0]
                    account_raw = parts[1]
                    stat = parts[2]
                    nick_match = re.search(r"\[(.*?)\]", account_raw)
                    handle_match = re.search(r"@([A-Za-z0-9_]+)", account_raw)
                    nick = nick_match.group(1) if nick_match else account_raw
                    handle = handle_match.group(1) if handle_match else ""
                    champions[dim] = {
                        "dimension": dim,
                        "nick": nick,
                        "handle": handle,
                        "stat": stat,
                    }

        growth_top10: List[Dict[str, Any]] = []
        growth_section = re.search(
            r"##\s*涨粉榜前十\s*\n\s*\|[^\n]+\n\s*\|[^\n]+\n((?:\|[^\n]+\n?)+)",
            md_text,
        )
        if growth_section:
            for line in growth_section.group(1).strip().split("\n"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 4:
                    rank_str = parts[0]
                    account_raw = parts[1]
                    gain_str = parts[2]
                    total_str = parts[3]
                    nick_match = re.search(r"\[(.*?)\]", account_raw)
                    handle_match = re.search(r"@([A-Za-z0-9_]+)", account_raw)
                    url_match = re.search(r"\((https?://[^\)]+)\)", account_raw)
                    growth_top10.append({
                        "rank": int(rank_str) if rank_str.isdigit() else len(growth_top10) + 1,
                        "nick": nick_match.group(1) if nick_match else account_raw,
                        "handle": handle_match.group(1) if handle_match else "",
                        "gain": gain_str,
                        "total_followers": total_str,
                        "url": url_match.group(1) if url_match else "",
                    })

        impression_top10: List[Dict[str, Any]] = []
        impr_section = re.search(
            r"##\s*推文曝光榜前十\s*\n\s*\|[^\n]+\n\s*\|[^\n]+\n((?:\|[^\n]+\n?)+)",
            md_text,
        )
        if impr_section:
            for line in impr_section.group(1).strip().split("\n"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    rank_str = parts[0]
                    account_raw = parts[1]
                    impr_str = parts[2]
                    nick_match = re.search(r"\[(.*?)\]", account_raw)
                    handle_match = re.search(r"@([A-Za-z0-9_]+)", account_raw)
                    url_match = re.search(r"\((https?://[^\)]+)\)", account_raw)
                    impression_top10.append({
                        "rank": int(rank_str) if rank_str.isdigit() else len(impression_top10) + 1,
                        "nick": nick_match.group(1) if nick_match else account_raw,
                        "handle": handle_match.group(1) if handle_match else "",
                        "impressions": impr_str,
                        "url": url_match.group(1) if url_match else "",
                    })

        viral_posts: List[Dict[str, Any]] = []
        viral_matches = re.findall(
            r"(\d+)\.\s*\*\*(.*?)\*\*\s*（(.*?)曝光）\[看原帖\]\((https?://x\.com/[^\)]+)\)\s*\n\s*>\s*(.*?)(?=\n\s*\d+\.|\n\s*---|\Z)",
            md_text,
            re.DOTALL,
        )
        for rank_str, author, heat_str, link, text in viral_matches:
            handle_match = re.search(r"https?://x\.com/([A-Za-z0-9_]+)/status/", link)
            handle = handle_match.group(1) if handle_match else ""
            clean_text = re.sub(r"\s+", " ", text).strip()
            viral_posts.append({
                "rank": int(rank_str) if rank_str.isdigit() else len(viral_posts) + 1,
                "author": author.strip(),
                "handle": handle,
                "impressions": heat_str.strip(),
                "link": link.strip(),
                "text": clean_text,
            })

        return {
            "date": snapshot_date,
            "champions": champions,
            "growth_top10": growth_top10,
            "impression_top10": impression_top10,
            "viral_posts": viral_posts,
        }

    def fetch_snapshot(self, force_refresh: bool = False, target_date: Optional[str] = None) -> Dict[str, Any]:
        """获取完整榜单快照（优先本地缓存）."""
        if not force_refresh and not target_date:
            cached = self._load_cache()
            if cached:
                return cached

        md_text = self.fetch_markdown(target_date)
        data = self.parse_markdown(md_text)
        if data and (data.get("growth_top10") or data.get("viral_posts")):
            self._save_cache(data)
            return data

        cached = self._load_cache()
        if cached:
            return cached

        fallback_data = self.parse_markdown(FALLBACK_SNAPSHOT_MD)
        return fallback_data

    def get_target_handles(self, limit: int = 20) -> List[str]:
        """提取全部高价值互动目标博主 Handles（去重排序）."""
        snapshot = self.fetch_snapshot()
        handles: List[str] = []
        seen = set()

        for c in snapshot.get("champions", {}).values():
            h = c.get("handle")
            if h and h.lower() not in seen:
                seen.add(h.lower())
                handles.append(h)

        for item in snapshot.get("growth_top10", []):
            h = item.get("handle")
            if h and h.lower() not in seen:
                seen.add(h.lower())
                handles.append(h)

        for item in snapshot.get("impression_top10", []):
            h = item.get("handle")
            if h and h.lower() not in seen:
                seen.add(h.lower())
                handles.append(h)

        for item in snapshot.get("viral_posts", []):
            h = item.get("handle")
            if h and h.lower() not in seen:
                seen.add(h.lower())
                handles.append(h)

        return handles[:limit]

    def get_viral_topics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """将 X 爆款推文转化为与 TopHub 题材库同结构的题材条目，供给 posting_engine."""
        snapshot = self.fetch_snapshot()
        posts = snapshot.get("viral_posts", [])
        topics = []
        for p in posts[:limit]:
            raw_text = p.get("text", "")
            first_sentence = raw_text.split("。")[0].split("？")[0].split("！")[0]
            if len(first_sentence) < 6 and len(raw_text) > 10:
                first_sentence = raw_text[:28]

            title = first_sentence.strip() or raw_text[:25].strip()
            topics.append({
                "title": title,
                "full_text": raw_text,
                "source": "X榜单",
                "category": "tech_ai",
                "heat": f"{p.get('impressions', '')}曝光",
                "rank": p.get("rank", 1),
                "author": p.get("author", ""),
                "handle": p.get("handle", ""),
                "link": p.get("link", ""),
            })
        return topics
