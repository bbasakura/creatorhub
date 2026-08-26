import json
import tempfile
import unittest
from pathlib import Path

import app.db as db
from app.engine.monitor import MonitorEngine
from app.main import app
from app.models import ContentRecord, PublishTask
from app.platforms.wechat_mp.extract import (
    parse_mp_feed,
    parse_mp_comment,
    flatten_mp_comments,
    parse_self_user,
)
from app.platforms.wechat_mp.resolve import (
    resolve_mp_user_id,
    resolve_mp_article_id,
    looks_like_article,
)
from app.platforms.wechat_mp.publish import _markdown_to_wechat_html
from app.browser.login import _mp_login_ready


class WechatMpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._previous_engine = db._engine
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "wechat_mp_test.db"
        db.init_db(str(self.db_path))

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = self._previous_engine
        self._tmp.cleanup()

    def test_wechat_mp_routes_are_registered(self):
        routes = {
            (route.path, method)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("/api/login/wechat_mp/start", "POST"), routes)
        self.assertIn(("/api/contents/{cid}/repost-wechat_mp", "POST"), routes)

    def test_relay_task_targets_wechat_mp(self):
        media = Path(self._tmp.name) / "article_cover.jpg"
        media.write_bytes(b"image")
        with db.get_session() as session:
            record = ContentRecord(
                platform="xhs",
                target_id=1,
                aweme_id="note-12345",
                desc="小红书爆款图文正文",
                media_type="images",
                download_status="done",
                local_path=str(media),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            content_id = record.id

        engine = MonitorEngine.__new__(MonitorEngine)
        task_id = engine.create_relay_publish(
            content_id,
            account_id=888,
            target_platform="wechat_mp",
            title="微信公众号测试标题",
            desc="微信公众号测试排版正文",
            topics="AI,短视频",
        )

        self.assertIsNotNone(task_id)
        with db.get_session() as session:
            task = session.get(PublishTask, task_id)
            self.assertEqual(task.platform, "wechat_mp")
            self.assertEqual(task.account_id, 888)
            self.assertEqual(task.source_platform, "xhs")
            self.assertEqual(task.source_content_id, content_id)
            self.assertEqual(task.title, "微信公众号测试标题")
            self.assertEqual(json.loads(task.media_json), [str(media)])


class WechatMpExtractAndResolveTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_mp_feed_article(self):
        sample = {
            "appmsgid": 100012345,
            "title": "深度剖析：AI Agent 的演进",
            "digest": "本文带你全方位解析 Agent 架构",
            "author_name": "极客观察",
            "cover": "http://mmbiz.qpic.cn/mmbiz_jpg/test/0",
            "create_time": 1756200000,
            "read_num": 12500,
            "like_num": 340,
            "old_like_num": 120,
            "comment_num": 45,
            "appmsg_type": 9,
        }
        feed = parse_mp_feed(sample)
        self.assertIsNotNone(feed)
        self.assertEqual(feed.aweme_id, "100012345")
        self.assertEqual(feed.author_name, "极客观察")
        self.assertEqual(feed.like_count, 460)  # like + old_like
        self.assertEqual(feed.comment_count, 45)
        self.assertEqual(feed.platform, "wechat_mp")

    def test_parse_mp_feed_images(self):
        sample = {
            "appmsgid": "img_post_999",
            "title": "精选壁纸贴图集",
            "digest": "九张高清唯美画质",
            "cover": "http://mmbiz.qpic.cn/cover.jpg",
            "picture_list": [
                {"cdn_url": "http://mmbiz.qpic.cn/pic1.jpg"},
                {"cdn_url": "http://mmbiz.qpic.cn/pic2.jpg"}
            ],
            "appmsg_type": 10,
        }
        feed = parse_mp_feed(sample)
        self.assertIsNotNone(feed)
        self.assertEqual(feed.media_type, "images")
        self.assertTrue(len(feed.medias) >= 2)

    def test_parse_mp_comment(self):
        sample = {
            "comment_id": 8801,
            "content": "这篇文章写得太透彻了！",
            "nick_name": "读者小王",
            "like_num": 18,
            "create_time": 1756201000,
            "is_elected": 1,
            "is_top": 0,
        }
        c = parse_mp_comment(sample)
        self.assertIsNotNone(c)
        self.assertEqual(c["comment_id"], "8801")
        self.assertEqual(c["user_nickname"], "读者小王")
        self.assertEqual(c["like_count"], 18)
        self.assertTrue(c["is_elected"])

    def test_parse_self_user(self):
        u = {
            "data": {
                "user_info": {
                    "nickname": "科技先锋号",
                    "user_name": "gh_123456789abc",
                    "alias": "tech_pioneer",
                    "fakeid": "2390123456",
                    "head_img": "http://wx.qlogo.cn/mmopen/avatar.png",
                    "total_user": 58900,
                    "appmsg_cnt": 142,
                }
            }
        }
        user = parse_self_user(u)
        self.assertEqual(user["nickname"], "科技先锋号")
        self.assertEqual(user["sec_uid"], "2390123456")
        self.assertEqual(user["douyin_id"], "tech_pioneer")
        self.assertEqual(user["follower_count"], 58900)
        self.assertEqual(user["aweme_count"], 142)

    async def test_resolve_mp_ids(self):
        gh = await resolve_mp_user_id("欢迎关注公众号 gh_9876543210ab")
        self.assertEqual(gh, "gh_9876543210ab")

        art_id = await resolve_mp_article_id("https://mp.weixin.qq.com/s/abcdef123456_-xyz")
        self.assertEqual(art_id, "abcdef123456_-xyz")

        self.assertTrue(looks_like_article("https://mp.weixin.qq.com/s/abcdef"))
        self.assertFalse(looks_like_article("gh_9876543210ab"))

    def test_markdown_to_wechat_html(self):
        md = "# 标题一\n## 标题二\n> 这是引文\n\n**重点内容**正文。"
        html = _markdown_to_wechat_html(md)
        self.assertIn("<h2", html)
        self.assertIn("#07c160", html)
        self.assertIn("<blockquote", html)
        self.assertIn("<strong", html)

    def test_mp_login_ready(self):
        self.assertTrue(
            _mp_login_ready({"slave_user", "slave_sid"}, "https://mp.weixin.qq.com/cgi-bin/home?token=123456")
        )
        self.assertFalse(
            _mp_login_ready({"slave_user"}, "https://mp.weixin.qq.com/login.html")
        )


if __name__ == "__main__":
    unittest.main()

