import unittest
from unittest.mock import patch

from app.models import AccountActionTask, CommentTask, PublishTask
from app.services.task_uncertainty import (
    UncertainVerificationError,
    apply_uncertain_resolution,
    automatic_uncertain_evidence,
)


class TaskUncertaintyTests(unittest.TestCase):
    def test_stored_publish_result_is_strong_auto_evidence(self):
        task = PublishTask(id=3, platform="wechat_mp", status="uncertain",
                           platform_result_id="draft-1", result_url="https://example/#draft=draft-1")
        evidence = automatic_uncertain_evidence(task, "publishes")
        self.assertTrue(evidence["confirmed"])
        self.assertEqual(evidence["result_id"], "draft-1")

    def test_youtube_video_id_record_is_strong_auto_evidence(self):
        task = PublishTask(id=8, platform="youtube", status="uncertain")
        with patch("app.platforms.youtube.client.load", return_value={"video_id": "abc123"}):
            evidence = automatic_uncertain_evidence(task, "publishes")
        self.assertTrue(evidence["confirmed"])
        self.assertIn("abc123", evidence["result_url"])

    def test_comment_never_auto_confirms_from_weak_local_fields(self):
        task = CommentTask(status="uncertain", result="maybe")
        self.assertFalse(automatic_uncertain_evidence(task, "comments")["confirmed"])

    def test_manual_done_moves_uncertain_to_done_without_retry(self):
        task = AccountActionTask(account_id=1, status="uncertain", error="write_uncertain:x")
        apply_uncertain_resolution(task, "actions", "confirmed_done")
        self.assertEqual(task.status, "done")
        self.assertEqual(task.error, "")
        self.assertIsNotNone(task.done_at)

    def test_confirmed_not_done_becomes_retryable_failed(self):
        task = PublishTask(status="uncertain", error="write_uncertain:x")
        apply_uncertain_resolution(task, "publishes", "confirmed_not_done", note="平台列表无记录")
        self.assertEqual(task.status, "failed")
        self.assertIn("平台列表无记录", task.error)

    def test_non_uncertain_task_cannot_be_resolved(self):
        with self.assertRaises(UncertainVerificationError):
            apply_uncertain_resolution(PublishTask(status="failed"), "publishes", "confirmed_done")


if __name__ == "__main__":
    unittest.main()
