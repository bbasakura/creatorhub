"""Unit tests for TopHub crawler and X post generation engine."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.platforms.x.tophub_crawler import TopHubCrawler, FALLBACK_TOPICS
from app.platforms.x.posting_engine import XPostingEngine, format_title_for_post


SAMPLE_TOPHUB_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="cc-cd">
    <div class="cc-cd-lb">知乎</div>
    <div class="cc-cd-cb-l">
      <a href="https://zhihu.com/q/123">
        <div class="cc-cd-cb-ll">
          <span class="s h">1</span>
          <span class="t">多地贷款中介集体解散群聊、删除朋友圈，背后原因是什么？</span>
          <span class="e">450 万热度</span>
        </div>
      </a>
      <a href="https://zhihu.com/q/124">
        <div class="cc-cd-cb-ll">
          <span class="s">2</span>
          <span class="t">大城市还是回老家？年轻人每月跨城通勤两小时算划算吗？</span>
          <span class="e">380 万热度</span>
        </div>
      </a>
    </div>
  </div>

  <div class="cc-cd">
    <div class="cc-cd-lb">36氪</div>
    <div class="cc-cd-cb-l">
      <a href="https://36kr.com/p/999">
        <div class="cc-cd-cb-ll">
          <span class="s h">1</span>
          <span class="t">单月收入破千万，AI应用公司智灵新境完成数千万元天使轮融资</span>
          <span class="e">独家</span>
        </div>
      </a>
    </div>
  </div>

  <div class="cc-cd">
    <div class="cc-cd-lb">淘宝 ‧ 天猫</div>
    <div class="cc-cd-cb-l">
      <a href="https://remai.today/item/1">
        <div class="cc-cd-cb-ll">
          <span class="s">1</span>
          <span class="t">得力A4护眼复印纸 券后¥3.9</span>
          <span class="e">热销</span>
        </div>
      </a>
    </div>
  </div>
</body>
</html>
"""


class TestTopHubCrawler(unittest.TestCase):
    """测试 TopHub 爬虫解析、分类与缓存机制."""

    def setUp(self):
        self.test_cache_file = os.path.join(_PROJECT_ROOT, "runtime", "test_tophub_cache.json")
        if os.path.exists(self.test_cache_file):
            os.remove(self.test_cache_file)
        self.crawler = TopHubCrawler(cache_ttl_seconds=300, cache_file=self.test_cache_file)

    def tearDown(self):
        if os.path.exists(self.test_cache_file):
            try:
                os.remove(self.test_cache_file)
            except Exception:
                pass

    def test_parse_html_and_filtering(self):
        topics = self.crawler._parse_html(SAMPLE_TOPHUB_HTML)
        self.assertEqual(len(topics), 3)

        # 检查知乎条目
        t1 = topics[0]
        self.assertEqual(t1["source"], "知乎")
        self.assertEqual(t1["category"], "workplace_career")
        self.assertEqual(t1["rank"], 1)
        self.assertIn("贷款中介", t1["title"])
        self.assertEqual(t1["heat"], "450 万热度")

        # 检查36氪科技条目
        t2 = topics[2]
        self.assertEqual(t2["source"], "36氪")
        self.assertEqual(t2["category"], "tech_ai")
        self.assertIn("AI应用", t2["title"])

        # 验证淘宝电商节点已完全过滤
        sources = [t["source"] for t in topics]
        self.assertNotIn("淘宝 ‧ 天猫", sources)

    @patch.object(TopHubCrawler, "_fetch_html", return_value=SAMPLE_TOPHUB_HTML)
    def test_fetch_topics_and_categories(self, mock_fetch):
        # 强制刷新
        topics = self.crawler.fetch_topics(force_refresh=True)
        self.assertGreaterEqual(len(topics), 3)

        # 按分类筛选
        ai_topics = self.crawler.get_topics_by_category("tech_ai")
        self.assertTrue(all(t["category"] == "tech_ai" for t in ai_topics))

        career_topics = self.crawler.get_topics_by_category("workplace_career")
        self.assertTrue(all(t["category"] == "workplace_career" for t in career_topics))

    @patch.object(TopHubCrawler, "_fetch_from_dailyhot_api", return_value=[])
    @patch.object(TopHubCrawler, "_fetch_html", side_effect=RuntimeError("Network down"))
    @patch.object(TopHubCrawler, "_load_cache", return_value=None)
    def test_fallback_on_network_failure(self, mock_cache, mock_fetch, mock_dailyhot):
        # 网络异常且无缓存时，必须优雅降级返回 fallback 话题
        topics = self.crawler.fetch_topics(force_refresh=True)
        self.assertEqual(topics, FALLBACK_TOPICS)
        self.assertGreater(len(topics), 0)


class TestXPostingEngineWithTopHub(unittest.TestCase):
    """测试 X 发帖引擎与 TopHub 题材融合."""

    def setUp(self):
        self.crawler = TopHubCrawler()
        self.engine = XPostingEngine(crawler=self.crawler)

    def test_format_title_for_post(self):
        # 短标题无需换行
        short = "鲍师傅超长蛋挞被吐槽"
        res_short = format_title_for_post(short)
        self.assertEqual(res_short, f"「{short}」")

        # 超长标题智能分行，且各行不超过 32 个字
        long_title = "8点1氪丨遭实名举报偷税漏税，罗永浩回应；段永平买入3万股贵州茅台；比尔盖茨发出严厉警告：AI或足以造成10亿人死亡"
        res_long = format_title_for_post(long_title)
        self.assertTrue(res_long.startswith("「") and res_long.endswith("」"))
        for line in res_long.split("\n"):
            self.assertLessEqual(len(line), 32)

    def test_generate_post_from_topic(self):
        topic = {
            "title": "单月收入破千万，AI应用公司完成数千万元天使轮融资",
            "source": "36氪",
            "category": "tech_ai",
            "rank": 1,
            "heat": "独家",
        }
        post = self.engine.generate_post_from_topic(topic)
        self.assertIn("单月收入破千万", post)
        val = self.engine.validate_post(post)
        self.assertTrue(val["valid"], f"Validation failed: {val['reason']}")

    def test_generate_hot_post(self):
        result = self.engine.generate_hot_post(category="tech_ai")
        self.assertIn("post_text", result)
        self.assertIn("topic", result)
        self.assertTrue(result["valid"], f"Generated invalid post: {result['reason']}")
        self.assertLessEqual(result["character_count"], 280)

    def test_recommend_daily_topics(self):
        recs = self.engine.recommend_daily_topics(limit=3)
        self.assertGreaterEqual(len(recs), 1)
        for r in recs:
            self.assertIn("title", r)
            self.assertIn("post_draft", r)
            self.assertTrue(r["valid"])

    def test_validate_post_safety_and_rules(self):
        # 空内容失败
        self.assertFalse(self.engine.validate_post("")["valid"])

        # 超过 280 字符失败
        long_post = "a" * 285
        self.assertFalse(self.engine.validate_post(long_post)["valid"])

        # 单行超 35 字符失败
        single_long_line = "今天" * 20
        self.assertFalse(self.engine.validate_post(single_long_line)["valid"])

        # AI 腔违禁词拦截
        ai_flavor_post = "今天刷到一个热搜：\n\n综上所述，AI在快速发展。"
        res = self.engine.validate_post(ai_flavor_post)
        self.assertFalse(res["valid"])
        self.assertIn("综上所述", res["reason"])


class TestFeishuTopicSync(unittest.TestCase):
    """测试飞书备选题材库同步器."""

    @patch("app.platforms.x.feishu_sync.XFeishuSync._api_request")
    def test_record_candidate_topic(self, mock_api):
        mock_api.return_value = {"code": 0, "msg": "success"}
        from app.platforms.x.feishu_sync import XFeishuSync

        sync = XFeishuSync()
        ok = sync.record_candidate_topic(
            title="测试题材",
            source="36氪",
            category="tech_ai",
            rank=1,
            heat="100万",
            link="https://36kr.com",
            post_draft="测试草稿内容",
        )
        self.assertTrue(ok)
        self.assertTrue(mock_api.called)
        args, kwargs = mock_api.call_args
        body = kwargs.get("body", {})
        fields = body.get("fields", {})
        self.assertEqual(fields["题材标题"], "测试题材")
        self.assertEqual(fields["分类"], "科技/AI")
        self.assertEqual(fields["来源平台"], "36氪")
        self.assertEqual(fields["采纳状态"], "待选")

    @patch("app.platforms.x.feishu_sync.XFeishuSync._api_request")
    def test_batch_record_candidate_topics(self, mock_api):
        mock_api.return_value = {
            "code": 0,
            "data": {"records": [{"record_id": "rec1"}, {"record_id": "rec2"}]},
        }
        from app.platforms.x.feishu_sync import XFeishuSync

        sync = XFeishuSync()
        items = [
            {"title": "题材1", "source": "知乎", "category": "workplace_career"},
            {"title": "题材2", "source": "微博", "category": "hot_buzz"},
        ]
        res = sync.batch_record_candidate_topics(items)
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["synced"], 2)
        self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()
