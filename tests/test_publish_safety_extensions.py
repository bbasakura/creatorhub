import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platforms.wechat_mp.draft_safety import saved_draft_id, matches_draft
from app.platforms.wechat_mp.publish import publish_mp, _markdown_to_wechat_html
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

    async def test_unverified_types_and_publish_fail_closed(self):
        for kind in ['images', 'video']:
            ok, _, _ = await publish_mp(None, None, '', 'title', 'body', media_type=kind)
            self.assertFalse(ok)
        ok, _, _ = await publish_mp(None, None, '', 'title', 'body', publish_mode='publish')
        self.assertFalse(ok)

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
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ValueError):
                client.start_oauth()
