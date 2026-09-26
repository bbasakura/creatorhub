import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platforms.wechat_mp.draft_safety import (
    saved_draft_id, matches_draft, matches_draft_type,
)
from app.platforms.wechat_mp.publish import (
    MP_DRAFT_TYPES, _is_podcast_editor, _markdown_to_wechat_html,
    _normalize_mp_type, publish_mp,
)
from app.platforms.youtube import client


class DraftEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def test_success_code_without_id_is_not_evidence(self):
        self.assertEqual(saved_draft_id({'base_resp': {'ret': 0}}), '')

    def test_error_with_id_is_not_success(self):
        self.assertEqual(saved_draft_id({'appMsgId': '1', 'base_resp': {'ret': 1}}), '')

    def test_match_requires_id_and_title(self):
        data = {'app_msg_list': [{'app_msg_id': '1', 'title': 'hello'}]}
        self.assertTrue(matches_draft(data, '1', 'hello'))
        self.assertFalse(matches_draft(data, '2', 'hello'))
        self.assertFalse(matches_draft(data, '1', 'other'))

    def test_video_type_requires_explicit_type_evidence(self):
        video = {'app_msg_list': [{'app_msg_id': '1', 'title': 'v', 'appmsg_type': 15}]}
        article = {'app_msg_list': [{'app_msg_id': '1', 'title': 'v', 'appmsg_type': 9}]}
        missing = {'app_msg_list': [{'app_msg_id': '1', 'title': 'v'}]}
        self.assertTrue(matches_draft_type(video, '1', 'v', 15))
        self.assertFalse(matches_draft_type(article, '1', 'v', 15))
        self.assertFalse(matches_draft_type(missing, '1', 'v', 15))

    def test_mp_business_categories_are_stable(self):
        self.assertEqual(MP_DRAFT_TYPES, {'article', 'images', 'video', 'podcast'})
        self.assertEqual(_normalize_mp_type('text'), 'article')
        self.assertEqual(_normalize_mp_type('tietu'), 'images')
        self.assertEqual(_normalize_mp_type('podcast'), 'podcast')
        self.assertEqual(_normalize_mp_type('video'), 'video')

    async def test_unverified_types_and_publish_fail_closed(self):
        for kind in ['images', 'video', 'podcast']:
            ok, _, _ = await publish_mp(None, None, '', 'title', 'body', media_type=kind)
            self.assertFalse(ok)
        ok, _, _ = await publish_mp(None, None, '', 'title', 'body', publish_mode='publish')
        self.assertFalse(ok)

    async def test_podcast_requires_native_editor_and_audio(self):
        page = unittest.mock.Mock()
        page.url = 'https://mp.weixin.qq.com/cgi-bin/appmsg?createType=7'
        page.locator.return_value.first.wait_for = unittest.mock.AsyncMock()
        self.assertTrue(await _is_podcast_editor(page))
        page.url = 'https://mp.weixin.qq.com/cgi-bin/appmsg?type=77'
        self.assertFalse(await _is_podcast_editor(page))
        ok, _, error = await publish_mp(None, None, '', 'title', 'body', media_type='podcast')
        self.assertFalse(ok)
        self.assertIn('missing_audio', error)

    def test_html_is_escaped(self):
        self.assertNotIn('<script>', _markdown_to_wechat_html('<script>alert(1)</script>'))


class YoutubeCredentialTests(unittest.TestCase):
    def test_state_storage_and_reference_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(client, 'ROOT', Path(directory)):
            client.store('test', {'value': 1})
            self.assertEqual(client.load('test'), {'value': 1})
            with self.assertRaises(ValueError):
                client.store('../secret', {})

    def test_oauth_requires_configuration(self):
        # OAuth credentials may legitimately come from env or config.yaml.
        # Isolate this test from the developer machine's real configuration.
        with patch.object(client, 'get_client_credentials', return_value=('', '')):
            with self.assertRaises(ValueError):
                client.start_oauth()
