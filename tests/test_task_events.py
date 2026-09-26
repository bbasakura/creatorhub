import json
import unittest

from app.models import TaskEvent
from app.services.task_events import add_task_event, task_event_dict


class FakeSession:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)


class TaskEventTests(unittest.TestCase):
    def test_event_serialization_is_structured(self):
        session = FakeSession()
        event = add_task_event(
            session, queue_type="publishes", row_id=9,
            event_type="control:retry", from_status="failed",
            to_status="pending", actor="tester",
            metadata={"reason": "manual"},
        )
        self.assertEqual(session.rows, [event])
        self.assertEqual(json.loads(event.metadata_json)["reason"], "manual")
        payload = task_event_dict(event)
        self.assertEqual(payload["event_type"], "control:retry")
        self.assertEqual(payload["from_status"], "failed")
        self.assertEqual(payload["to_status"], "pending")
        self.assertEqual(payload["metadata"]["reason"], "manual")


if __name__ == "__main__":
    unittest.main()
