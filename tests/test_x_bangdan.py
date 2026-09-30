"""Unit tests for XBangDan (xbangdan.com) crawler, posting engine, and stream replier."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.platforms.x.xbangdan_crawler import XBangDanCrawler, FALLBACK_SNAPSHOT_MD
from app.platforms.x.posting_engine import XPostingEngine
from app.platforms.x.stream_replier import XStreamReplier


SAMPLE_MD = """# X榜单 · 2026-09-29

## 四个维度的冠军

| 维度 | 账号 | 数据 |
| --- | --- | --- |
| 发帖 | [测试发帖王](https://xbangdan.com/account/poster1/) @poster1 | 99 帖 |
| 涨粉 | [测试涨粉星](https://xbangdan.com/account/grower1/) @grower1 | +1234 粉 |

## 涨粉榜前十

| # | 账号 | 涨粉 | 总粉丝 |
| --- | --- | --- | --- |
| 1 | [测试涨粉星](https://xbangdan.com/account/grower1/) @grower1 | +1234 | 10.0 万 |
| 2 | [第二名](https://xbangdan.com/account/second_grow/) @second_grow | +999 | 5.0 万 |

## 推文曝光榜前十

| # | 账号 | 当日曝光 |
| --- | --- | --- |
| 1 | [曝光王](https://xbangdan.com/account/impr_king/) @impr_king | 100.0 万 |

## 24 小时最爆推文

1. **爆款作者A** （150.0 万 曝光）[看原帖](https://x.com/viral_a/status/123456789)
   > 真实做内容的痛点：工具越用越多，结果写出的东西越来越像流水线。你怎么看？

2. **爆款作者B** （80.0 万 曝光）[看原帖](https://x.com/viral_b/status/987654321)
   > 聊聊独立开发出海的坑。第一天千万不要做大而全的产品！
"""


class TestXBangDanCrawler(unittest.TestCase):
    def setUp(self):
        self.test_cache_file = os.path.join(_PROJECT_ROOT, "runtime", "test_xbangdan_cache.json")
        if os.path.exists(self.test_cache_file):
            os.remove(self.test_cache_file)
        self.crawler = XBangDanCrawler(cache_ttl_seconds=300, cache_file=self.test_cache_file)

    def tearDown(self):
        if os.path.exists(self.test_cache_file):
            try:
                os.remove(self.test_cache_file)
            except Exception:
                pass

    def test_parse_markdown_structure(self):
        data = self.crawler.parse_markdown(SAMPLE_MD)
        self.assertEqual(data["date"], "2026-09-29")
        self.assertIn("发帖", data["champions"])
        self.assertEqual(data["champions"]["发帖"]["handle"], "poster1")
        self.assertEqual(data["champions"]["发帖"]["nick"], "测试发帖王")

        # 涨粉榜
        self.assertEqual(len(data["growth_top10"]), 2)
        self.assertEqual(data["growth_top10"][0]["handle"], "grower1")
        self.assertEqual(data["growth_top10"][0]["gain"], "+1234")

        # 爆款推文
        self.assertEqual(len(data["viral_posts"]), 2)
        self.assertEqual(data["viral_posts"][0]["author"], "爆款作者A")
        self.assertEqual(data["viral_posts"][0]["handle"], "viral_a")
        self.assertIn("真实做内容的痛点", data["viral_posts"][0]["text"])

    def test_target_handles_deduplication(self):
        with patch.object(self.crawler, "fetch_markdown", return_value=SAMPLE_MD):
            handles = self.crawler.get_target_handles(limit=10)
            self.assertIn("poster1", handles)
            self.assertIn("grower1", handles)
            self.assertIn("impr_king", handles)
            self.assertIn("viral_a", handles)
            # 保证去重
            self.assertEqual(len(handles), len(set(handles)))

    def test_viral_topics_extraction(self):
        with patch.object(self.crawler, "fetch_markdown", return_value=SAMPLE_MD):
            topics = self.crawler.get_viral_topics(limit=5)
            self.assertEqual(len(topics), 2)
            self.assertEqual(topics[0]["source"], "X榜单")
            self.assertEqual(topics[0]["handle"], "viral_a")
            self.assertIn("真实做内容的痛点", topics[0]["title"])

    def test_cache_mechanism(self):
        with patch.object(self.crawler, "fetch_markdown", return_value=SAMPLE_MD) as mock_fetch:
            # 首次读取拉取数据并写入缓存
            s1 = self.crawler.fetch_snapshot(force_refresh=False)
            self.assertEqual(s1["date"], "2026-09-29")
            self.assertEqual(mock_fetch.call_count, 1)

            # 第二次读取直接命中缓存，不重复请求
            s2 = self.crawler.fetch_snapshot(force_refresh=False)
            self.assertEqual(s2["date"], "2026-09-29")
            self.assertEqual(mock_fetch.call_count, 1)


class TestPostingEngineWithXBangDan(unittest.TestCase):
    def setUp(self):
        self.crawler = XBangDanCrawler(cache_file=os.path.join(_PROJECT_ROOT, "runtime", "test_cache_p.json"))
        self.engine = XPostingEngine(xbangdan_crawler=self.crawler)

    def test_generate_hot_post_from_xbangdan(self):
        with patch.object(self.crawler, "fetch_markdown", return_value=SAMPLE_MD):
            res = self.engine.generate_hot_post(prefer_x_native=True)
            self.assertEqual(res["topic"]["source"], "X榜单")
            self.assertTrue(res["valid"])
            self.assertTrue(
                "在推特上做内容最核心的一点" in res["post_text"]
                or "很多时候爆款不是靠碰运气" in res["post_text"]
            )
            self.assertLessEqual(len(res["post_text"]), 280)

    def test_recommend_daily_topics_with_xbangdan(self):
        with patch.object(self.crawler, "fetch_markdown", return_value=SAMPLE_MD):
            recs = self.engine.recommend_daily_topics(limit=3, include_x_native=True)
            self.assertGreaterEqual(len(recs), 2)
            sources = [r["source"] for r in recs]
            self.assertIn("X榜单", sources)


class TestStreamReplierWithXBangDan(unittest.TestCase):
    def test_filter_and_prioritize_target_creators(self):
        test_cache = os.path.join(_PROJECT_ROOT, "runtime", "test_cache_stream.json")
        if os.path.exists(test_cache):
            os.remove(test_cache)
        crawler = XBangDanCrawler(cache_file=test_cache)
        try:
            with patch.object(crawler, "fetch_markdown", return_value=SAMPLE_MD):
                replier = XStreamReplier(own_handle="sakurakk730", xbangdan_crawler=crawler)
                raw_tweets = [
                    {
                        "tweetLink": "https://x.com/random_user/status/111",
                        "authorHandle": "random_user",
                        "authorNick": "路人甲",
                        "tweetText": "今天天气不错",
                    },
                    {
                        "tweetLink": "https://x.com/grower1/status/222",
                        "authorHandle": "grower1",
                        "authorNick": "涨粉星",
                        "tweetText": "聊聊怎么做自媒体增长",
                    },
                ]
                candidates = replier.filter_raw_tweets(raw_tweets)
                self.assertEqual(len(candidates), 2)
                self.assertTrue(candidates[0]["isTargetCreator"])
                self.assertEqual(candidates[0]["authorHandle"], "grower1")
                self.assertFalse(candidates[1]["isTargetCreator"])
                self.assertEqual(candidates[1]["authorHandle"], "random_user")
        finally:
            if os.path.exists(test_cache):
                os.remove(test_cache)


if __name__ == "__main__":
    unittest.main()
