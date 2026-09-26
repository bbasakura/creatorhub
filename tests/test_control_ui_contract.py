import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")

    def test_risk_center_exposes_platform_hard_circuit(self):
        self.assertIn('id="risk-platform-circuit-status"', self.html)
        self.assertIn("openPlatformCircuit()", self.html)
        self.assertIn("clearPlatformCircuit()", self.html)
        self.assertIn('/api/risk-control/platform-circuits', self.js)
        self.assertNotIn('class="navitem notyt-only" data-tab="risk-control"', self.html)

    def test_task_queue_exposes_event_timeline(self):
        self.assertIn("showTaskQueueEvents", self.js)
        self.assertIn('/api/task-queue/${encodeURIComponent(queueType)}/${Number(id)}/events', self.js)
        self.assertIn('>时间线</button>', self.js)


if __name__ == "__main__":
    unittest.main()
