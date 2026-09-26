import unittest

from app.services.platform_capabilities import (
    media_capability,
    media_types_for,
    normalize_operation,
    normalize_visibility,
    supports_schedule,
    title_limit,
    visibility_allowed,
)


class PlatformCapabilitiesTests(unittest.TestCase):
    def test_wechat_mp_draft_categories_and_limits(self):
        self.assertEqual(
            media_types_for("wechat_mp"),
            ("article", "images", "video", "podcast"),
        )
        self.assertEqual(title_limit("wechat_mp", "article"), 64)
        self.assertEqual(title_limit("wechat_mp", "images"), 20)
        self.assertEqual(title_limit("wechat_mp", "video"), 64)
        self.assertEqual(title_limit("wechat_mp", "podcast"), 20)
        self.assertEqual(normalize_operation("wechat_mp", "publish"), "draft")
        podcast = media_capability("wechat_mp", "podcast")
        self.assertEqual(podcast.min_media, 1)
        self.assertEqual(podcast.max_media, 1)
        self.assertIn(".mp3", podcast.extensions)

    def test_youtube_defaults_public_and_unscheduled(self):
        self.assertEqual(media_types_for("youtube"), ("video",))
        self.assertEqual(title_limit("youtube", "video"), 100)
        self.assertEqual(normalize_visibility("youtube", "private", explicitly_set=False), "public")
        self.assertEqual(normalize_visibility("youtube", "unlisted", explicitly_set=True), "unlisted")
        self.assertEqual(normalize_visibility("youtube", "private", explicitly_set=True), "private")
        self.assertFalse(supports_schedule("youtube"))
        self.assertEqual(normalize_operation("youtube", "publish"), "upload")

    def test_generic_social_visibility_is_stable(self):
        for platform in ("xhs", "douyin", "kuaishou", "shipinhao"):
            self.assertEqual(media_types_for(platform), ("images", "video"))
            self.assertEqual(title_limit(platform, "video"), 20)
            self.assertTrue(visibility_allowed(platform, "private"))
            self.assertFalse(visibility_allowed(platform, "unlisted"))
            self.assertEqual(normalize_operation(platform, "garbage"), "publish")


if __name__ == "__main__":
    unittest.main()
