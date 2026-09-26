import unittest
from datetime import datetime, timedelta, timezone

from app.models import AccountActionTask, KeywordCollectionJob, PublishTask
from app.services.task_queue_actions import (
    QueueActionError,
    apply_queue_transition,
    available_queue_actions,
)


class TaskQueueActionsTests(unittest.TestCase):
    def test_available_actions_respect_blocked_and_uncertain(self):
        self.assertEqual(
            available_queue_actions("publishes", "pending", blocked_reason="risk"),
            ["resume", "cancel"],
        )
        self.assertEqual(available_queue_actions("publishes", "failed"), ["retry"])
        self.assertEqual(available_queue_actions("publishes", "uncertain"), [])
        self.assertEqual(available_queue_actions("collections", "running"), ["cancel"])
        self.assertEqual(available_queue_actions("monitor_downloads", "pending"), [])

    def test_resume_clears_block_without_rebuilding_task(self):
        task = PublishTask(
            status="pending",
            blocked_reason="risk",
            blocked_signal="rate_limit",
            next_allowed_at=(
                datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)),
        )
        apply_queue_transition(task, "publishes", "resume")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.blocked_reason, "")
        self.assertEqual(task.blocked_signal, "")
        self.assertIsNone(task.next_allowed_at)

    def test_retry_resets_failed_action(self):
        task = AccountActionTask(
            account_id=1,
            status="failed",
            error="network",
            blocked_reason="network",
        )
        apply_queue_transition(task, "actions", "retry")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.error, "")
        self.assertEqual(task.blocked_reason, "")

    def test_collection_running_cancel_is_cooperative(self):
        job = KeywordCollectionJob(
            account_id=1,
            status="running",
            current_step="抓取中",
        )
        apply_queue_transition(job, "collections", "cancel", now=datetime(2026, 1, 1))
        self.assertEqual(job.status, "running")
        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.current_step, "正在安全停止")

    def test_uncertain_never_retries_automatically(self):
        task = PublishTask(status="uncertain")
        with self.assertRaises(QueueActionError):
            apply_queue_transition(task, "publishes", "retry")
        with self.assertRaises(QueueActionError):
            apply_queue_transition(task, "publishes", "run-now")


if __name__ == "__main__":
    unittest.main()
