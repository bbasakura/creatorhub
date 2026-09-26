import unittest
from datetime import datetime, timedelta, timezone

from app.services.task_queue_view import queue_iso, queue_keywords, queue_state


class TaskQueueViewTests(unittest.TestCase):
    def test_queue_state_normalization(self):
        self.assertEqual(queue_state("failed"), "failed")
        self.assertEqual(queue_state("done"), "completed")
        self.assertEqual(queue_state("doing"), "running")
        self.assertEqual(queue_state("pending"), "pending")
        self.assertEqual(queue_state("pending", blocked_reason="cooldown"), "blocked")
        self.assertEqual(
            queue_state("pending", next_allowed_at=(
                datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1))),
            "blocked",
        )

    def test_queue_keywords_and_iso(self):
        self.assertEqual(queue_keywords('["防晒霜", " AI "]'), "防晒霜、AI")
        self.assertEqual(queue_keywords(""), "未命名关键词任务")
        self.assertEqual(queue_keywords("raw-value"), "raw-value")
        self.assertEqual(queue_iso(datetime(2026, 9, 23, 9, 30, 1)), "2026-09-23T09:30:01Z")
        self.assertIsNone(queue_iso(None))


if __name__ == "__main__":
    unittest.main()
