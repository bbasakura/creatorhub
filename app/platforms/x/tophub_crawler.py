"""TopHub (今日热榜) 抓取与题材库解析模块.

数据源: https://tophub.today/
聚合知乎、微博、36氪、Readhub、掘金、IT之家、虎嗅等主流节点热榜，
为 X (Twitter) 推文与评论提供实时热点素材。
"""

import os
import sys
import json
import time
import re
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.error

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
RUNTIME_DIR = os.path.join(_PROJECT_ROOT, "runtime")
CACHE_FILE = os.path.join(RUNTIME_DIR, "tophub_cache.json")

TOPHUB_URL = "https://tophub.today/"

# 来源分类定义
SOURCE_CATEGORIES = {
    "tech_ai": ["36氪", "Readhub", "掘金", "IT之家", "少数派", "GitHub", "V2EX", "CSDN", "开源中国"],
    "workplace_career": ["知乎", "虎嗅网", "36氪", "知乎日报", "雪球", "界面新闻", "澎湃新闻"],
    "hot_buzz": ["微博", "知乎", "百度", "微信", "百度贴吧", "抖音", "快手", "哔哩哔哩", "B站", "豆瓣"],
}

# 排除的纯电商带货/广告节点
EXCLUDED_SOURCES = [
    "淘宝", "天猫", "京东", "拼多多", "当当", "唯品会", "什么值得买", "聚划算", "券", "折扣", "返利", "实时榜中榜"
]

FALLBACK_TOPICS = [
    {
        "title": "单月收入破千万，AI应用公司完成数千万元天使轮融资",
        "source": "36氪",
        "category": "tech_ai",
        "heat": "独家首发",
        "rank": 1,
        "link": "https://36kr.com",
    },
    {
        "title": "多地贷款中介集体解散群聊、删除朋友圈，背后原因是什么？",
        "source": "知乎",
        "category": "workplace_career",
        "heat": "450万热度",
        "rank": 2,
        "link": "https://zhihu.com",
    },
    {
        "title": "AI Agent 与垂直落地：普通创业者真正的机会到底在哪？",
        "source": "虎嗅网",
        "category": "tech_ai",
        "heat": "热议",
        "rank": 3,
        "link": "https://huxiu.com",
    },
    {
        "title": "大城市还是回老家？年轻人每月跨城通勤两小时算划算吗？",
        "source": "知乎",
        "category": "workplace_career",
        "heat": "380万热度",
        "rank": 4,
        "link": "https://zhihu.com",
    },
    {
        "title": "鲍师傅超长蛋挞被吐槽全是皮没蛋液，网红单品如何避开营销反噬？",
        "source": "微博",
        "category": "hot_buzz",
        "heat": "120万讨论",
        "rank": 5,
        "link": "https://weibo.com",
    },
]


class TopHubCrawler:
    """今日热榜抓取器与题材库管理."""

    def __init__(self, cache_ttl_seconds: int = 900, cache_file: Optional[str] = None):
        self.cache_ttl = cache_ttl_seconds
        self.cache_file = cache_file or CACHE_FILE
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)

    def _fetch_html(self) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(TOPHUB_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="replace")

    def _load_cache(self) -> Optional[List[Dict[str, Any]]]:
        if not os.path.exists(self.cache_file):
            return None
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_at = data.get("cached_at", 0)
            if time.time() - cached_at < self.cache_ttl:
                return data.get("topics", [])
        except Exception:
            pass
        return None

    def _save_cache(self, topics: List[Dict[str, Any]]):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({"cached_at": time.time(), "topics": topics}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TopHubCrawler] 缓存写入失败: {e}", file=sys.stderr)

    @staticmethod
    def _strip_html(fragment: str) -> str:
        text = re.sub(r"<[^>]+>", "", fragment or "")
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _extract_class_text(cls, fragment: str, class_name: str) -> str:
        pattern = (
            r'<[^>]+class=["\'][^"\']*\b' + re.escape(class_name)
            + r'\b[^"\']*["\'][^>]*>(.*?)</[^>]+>'
        )
        match = re.search(pattern, fragment or "", re.I | re.S)
        return cls._strip_html(match.group(1)) if match else ""

    def _category_for_source(self, source_name: str) -> str:
        category = "hot_buzz"
        for cat, sources in SOURCE_CATEGORIES.items():
            if any(s.lower() in source_name.lower() for s in sources):
                category = cat
                break
        return category

    def _parse_html_without_bs4(self, html: str) -> List[Dict[str, Any]]:
        """Parse the stable TopHub card structure using stdlib-compatible regexes."""
        card_start = re.compile(
            r'(?=<div[^>]+class=["\'][^"\']*(?<![\w-])cc-cd(?![\w-])[^"\']*["\'])',
            re.I,
        )
        chunks = [chunk for chunk in card_start.split(html or "") if "cc-cd" in chunk]
        topics: List[Dict[str, Any]] = []
        for chunk in chunks:
            source_name = self._extract_class_text(chunk, "cc-cd-lb")
            if not source_name or any(exc in source_name for exc in EXCLUDED_SOURCES):
                continue
            category = self._category_for_source(source_name)
            body_match = re.search(
                r'<div[^>]+class=["\'][^"\']*\bcc-cd-cb-l\b[^"\']*["\'][^>]*>(.*)',
                chunk, re.I | re.S)
            body = body_match.group(1) if body_match else chunk
            for attrs, inner in re.findall(r'<a\b([^>]*)>(.*?)</a>', body, re.I | re.S):
                title = self._extract_class_text(inner, "t")
                if not title:
                    title = self._strip_html(inner)
                    title = re.sub(r"^\d+[\.、\s]*", "", title).strip()
                    title = re.sub(r"[\s\d\.]+万(?:热度)?$", "", title).strip()
                if not title or len(title) < 4:
                    continue
                if any(kw in title for kw in ["券后", "原价¥", "热销", "包邮", "满减"]):
                    continue
                rank_str = self._extract_class_text(inner, "s")
                digits = re.sub(r"\D", "", rank_str or "")
                rank = int(digits) if digits else 0
                heat = self._extract_class_text(inner, "e")
                href_match = re.search(r'href=["\']([^"\']*)["\']', attrs, re.I)
                link = href_match.group(1) if href_match else ""
                if link.startswith("/"):
                    link = f"https://tophub.today{link}"
                topics.append({
                    "title": title,
                    "source": source_name,
                    "category": category,
                    "heat": heat,
                    "rank": rank,
                    "link": link,
                })
        return topics

    def _parse_html_bs4(self, html: str) -> List[Dict[str, Any]]:
        if not BeautifulSoup:
            return []
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("div", class_="cc-cd")
        all_topics: List[Dict[str, Any]] = []

        for card in cards:
            head = card.find("div", class_="cc-cd-lb")
            if not head:
                continue
            source_name = head.get_text(strip=True)

            # 过滤纯电商带货节点
            if any(exc in source_name for exc in EXCLUDED_SOURCES):
                continue

            category = self._category_for_source(source_name)
            body = card.find("div", class_="cc-cd-cb-l")
            if not body:
                continue

            items = body.find_all("a")
            for item in items:
                span_t = item.find("span", class_="t")
                span_s = item.find("span", class_="s")
                span_e = item.find("span", class_="e")

                # 提取标题
                if span_t:
                    title = span_t.get_text(strip=True)
                else:
                    raw_text = item.get_text(strip=True)
                    title = re.sub(r"^\d+[\.、\s]*", "", raw_text).strip()
                    title = re.sub(r"[\s\d\.]+万(?:热度)?$", "", title).strip()

                if not title or len(title) < 4:
                    continue

                if any(kw in title for kw in ["券后", "原价¥", "热销", "包邮", "满减"]):
                    continue

                rank_str = span_s.get_text(strip=True) if span_s else "0"
                try:
                    rank = int(re.sub(r"\D", "", rank_str)) if rank_str else 0
                except ValueError:
                    rank = 0

                heat = span_e.get_text(strip=True) if span_e else ""
                link = item.get("href", "")
                if link.startswith("/"):
                    link = f"https://tophub.today{link}"

                all_topics.append({
                    "title": title,
                    "source": source_name,
                    "category": category,
                    "heat": heat,
                    "rank": rank,
                    "link": link,
                })

        return all_topics

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        # 优先使用 BeautifulSoup 解析完整卡片；无 BS4 时回退至正则解析
        if BeautifulSoup:
            topics = self._parse_html_bs4(html)
            if topics:
                return topics
        return self._parse_html_without_bs4(html) or FALLBACK_TOPICS

    def fetch_topics(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取题材库热点列表（优先缓存，带容错兜底）."""
        if not force_refresh:
            cached = self._load_cache()
            if cached:
                return cached

        try:
            html = self._fetch_html()
            topics = self._parse_html(html)
            if topics:
                self._save_cache(topics)
                return topics
        except Exception as e:
            print(f"[TopHubCrawler] 实时抓取失败，降级回退: {e}", file=sys.stderr)

        # 普通读取失败时可退到过期缓存；显式 force_refresh 则不复用旧结果。
        if not force_refresh and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cached_topics = data.get("topics", [])
                    if cached_topics:
                        return cached_topics
            except Exception:
                pass

        return FALLBACK_TOPICS

    def get_topics_by_category(self, category: str = "all", limit: int = 10) -> List[Dict[str, Any]]:
        """按分类获取题材热点 (tech_ai | workplace_career | hot_buzz | all)."""
        topics = self.fetch_topics()
        if category and category != "all":
            filtered = [t for t in topics if t.get("category") == category]
        else:
            filtered = topics

        # 优先选择有热度或排名前列的
        return filtered[:limit]
