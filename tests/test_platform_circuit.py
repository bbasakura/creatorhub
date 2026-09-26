import unittest
from datetime import datetime, timedelta

from sqlmodel import SQLModel, Session, create_engine

from app import db
from app.config import Config
from app.models import DouyinAccount
from app.risk import OperationKind, RiskController


class PlatformCircuitTests(unittest.TestCase):
    def setUp(self):
        self.old_engine = db._engine
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        db._engine = self.engine
        with Session(self.engine) as session:
            account = DouyinAccount(platform="douyin", nickname="test", status="active")
            session.add(account)
            session.commit()
            session.refresh(account)
            self.account_id = account.id
        self.cfg = Config()
        self.controller = RiskController(self.cfg)

    def tearDown(self):
        self.engine.dispose()
        db._engine = self.old_engine

    def test_hard_circuit_blocks_writes_but_not_reads(self):
        self.controller.open_platform_circuit(
            "douyin", reason="系统性风控", actor="test")
        write = self.controller.hard_preflight(self.account_id, OperationKind.PUBLISH)
        read = self.controller.hard_preflight(self.account_id, OperationKind.READ_LIGHT)
        self.assertFalse(write.allowed)
        self.assertEqual(write.signal, "platform_circuit_open")
        self.assertTrue(read.allowed)

    def test_hard_circuit_survives_policy_disabled(self):
        self.cfg.risk_control.enabled = False
        self.controller.update_policy(self.cfg.risk_control)
        self.controller.open_platform_circuit("douyin", reason="紧急停写")
        decision = self.controller.preflight(self.account_id, OperationKind.COMMENT)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.signal, "platform_circuit_open")

    def test_expired_circuit_no_longer_blocks(self):
        now = datetime(2026, 9, 26, 8, 0, 0)
        self.controller.open_platform_circuit(
            "douyin", reason="短时熔断", duration_seconds=60, now=now)
        decision = self.controller.hard_preflight(
            self.account_id, OperationKind.PUBLISH,
            now=now + timedelta(seconds=61))
        self.assertTrue(decision.allowed)

    def test_clear_reopens_writes(self):
        self.controller.open_platform_circuit("douyin", reason="人工停写")
        self.assertTrue(self.controller.clear_platform_circuit("douyin", actor="test"))
        decision = self.controller.hard_preflight(self.account_id, OperationKind.PUBLISH)
        self.assertTrue(decision.allowed)
        rows = self.controller.list_platform_circuits()
        self.assertEqual(rows[0]["platform"], "douyin")
        self.assertFalse(rows[0]["is_open"])


if __name__ == "__main__":
    unittest.main()
