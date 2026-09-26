import unittest
from pathlib import Path

from app.api.publish_contract import PublishIn
from app.services.platform_capabilities import normalize_visibility


ROOT = Path(__file__).resolve().parents[1]


class YoutubeUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")

    def test_omitted_visibility_normalizes_public(self):
        body = PublishIn(account_id=1, media_type="video")
        self.assertNotIn("visibility", body.model_fields_set)
        self.assertEqual(
            normalize_visibility("youtube", body.visibility, explicitly_set=False),
            "public",
        )

    def test_publish_form_defaults_public_and_exposes_thumbnail(self):
        public = '<option value="public" selected>公开 (public，默认)</option>'
        self.assertIn(public, self.html)
        self.assertIn('id="yt-thumbnail"', self.html)
        self.assertIn('accept="image/jpeg,image/png"', self.html)
        self.assertIn("thumbnail_path: thumbnailPath", self.js)

    def test_upload_status_and_resume_are_visible(self):
        self.assertIn("function youtubeUploadMeta", self.js)
        self.assertIn("存在可恢复上传会话", self.js)
        self.assertIn("恢复原上传", self.js)
        self.assertIn("/api/youtube/tasks/", self.js)
        self.assertIn("/resume", self.js)


if __name__ == "__main__":
    unittest.main()
