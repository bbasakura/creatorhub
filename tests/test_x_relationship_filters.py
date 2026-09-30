import asyncio
import unittest

from sqlmodel import SQLModel, Session, create_engine, select

from app import db, main
from app.models import (
    AccountActionTask, DouyinAccount, FollowEdge, XRelationshipBatch,
)
from app.services.x_relationship_batches import should_pause_relationship_batch


class XRelationshipFilterTests(unittest.TestCase):
    def setUp(self):
        self.old_engine = db._engine
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        db._engine = self.engine
        with Session(self.engine) as session:
            account = DouyinAccount(
                platform="x", nickname="tester", sec_uid="tester",
                status="active")
            session.add(account)
            session.commit()
            session.refresh(account)
            self.account_id = account.id

    def tearDown(self):
        self.engine.dispose()
        db._engine = self.old_engine

    def test_mutual_flags_are_recomputed_from_synced_snapshot_intersection(self):
        with Session(self.engine) as session:
            session.add(FollowEdge(
                platform="x", account_id=self.account_id,
                direction="following", uid="alice", sec_uid="alice",
                nickname="Alice", is_following=True))
            session.add(FollowEdge(
                platform="x", account_id=self.account_id,
                direction="following", uid="bob", sec_uid="bob",
                nickname="Bob", is_following=True))
            session.add(FollowEdge(
                platform="x", account_id=self.account_id,
                direction="fan", uid="alice", sec_uid="alice",
                nickname="Alice", is_following=False))
            session.commit()
            main._refresh_follow_mutuals(session, self.account_id)
            session.commit()

            rows = session.exec(select(FollowEdge).where(
                FollowEdge.account_id == self.account_id)).all()
            by_key = {(row.direction, row.sec_uid): row for row in rows}
            self.assertTrue(by_key[("following", "alice")].is_mutual)
            self.assertTrue(by_key[("fan", "alice")].is_mutual)
            self.assertTrue(by_key[("fan", "alice")].is_following)
            self.assertFalse(by_key[("following", "bob")].is_mutual)

    def test_batch_unfollow_only_queues_valid_selected_following_rows(self):
        with Session(self.engine) as session:
            alice = FollowEdge(
                platform="x", account_id=self.account_id,
                direction="following", uid="alice", sec_uid="alice",
                nickname="Alice", is_following=True)
            bob = FollowEdge(
                platform="x", account_id=self.account_id,
                direction="following", uid="bob", sec_uid="bob",
                nickname="Bob", is_following=True)
            session.add(alice)
            session.add(bob)
            session.commit()
            session.refresh(alice)
            session.refresh(bob)
            session.add(AccountActionTask(
                platform="x", account_id=self.account_id,
                action="unfollow", target_uid="bob", target_sec_uid="bob",
                target_nick="Bob", status="pending"))
            session.commit()
            alice_id, bob_id = alice.id, bob.id

        result = asyncio.run(main.create_account_actions_batch(main.BatchActionIn(
            account_id=self.account_id,
            action="unfollow",
            edge_ids=[alice_id, bob_id, 999999],
        )))
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["skipped"], 2)
        self.assertIsNotNone(result["batch_id"])

        with Session(self.engine) as session:
            tasks = session.exec(select(AccountActionTask).where(
                AccountActionTask.account_id == self.account_id,
                AccountActionTask.action == "unfollow")).all()
            self.assertEqual(len(tasks), 2)
            self.assertTrue(all(task.status == "pending" for task in tasks))
            self.assertEqual(
                {task.target_sec_uid for task in tasks}, {"alice", "bob"})
            batched = [task for task in tasks if task.batch_id is not None]
            self.assertEqual(len(batched), 1)
            self.assertEqual(batched[0].batch_id, result["batch_id"])
            self.assertGreaterEqual(batched[0].min_gap_seconds, 50)
            self.assertLessEqual(batched[0].min_gap_seconds, 70)
            batch = session.get(XRelationshipBatch, result["batch_id"])
            self.assertIsNotNone(batch)
            self.assertEqual(batch.status, "active")
            self.assertEqual(batch.requested_count, 3)
            self.assertEqual(batch.total_count, 1)
            self.assertEqual(batch.skipped_count, 2)


    def test_batch_followback_only_queues_unfollowed_fan_rows(self):
        with Session(self.engine) as session:
            alice = FollowEdge(
                platform="x", account_id=self.account_id,
                direction="fan", uid="alice", sec_uid="alice",
                nickname="Alice", is_following=False)
            bob = FollowEdge(
                platform="x", account_id=self.account_id,
                direction="fan", uid="bob", sec_uid="bob",
                nickname="Bob", is_following=True)
            carol = FollowEdge(
                platform="x", account_id=self.account_id,
                direction="fan", uid="carol", sec_uid="carol",
                nickname="Carol", is_following=False)
            wrong = FollowEdge(
                platform="x", account_id=self.account_id,
                direction="following", uid="wrong", sec_uid="wrong",
                nickname="Wrong", is_following=True)
            session.add(alice)
            session.add(bob)
            session.add(carol)
            session.add(wrong)
            session.commit()
            for edge in (alice, bob, carol, wrong):
                session.refresh(edge)
            session.add(AccountActionTask(
                platform="x", account_id=self.account_id,
                action="follow", target_uid="carol", target_sec_uid="carol",
                target_nick="Carol", status="pending"))
            session.commit()
            edge_ids = [alice.id, bob.id, carol.id, wrong.id]

        result = asyncio.run(main.create_account_actions_batch(main.BatchActionIn(
            account_id=self.account_id,
            action="follow",
            edge_ids=edge_ids,
        )))
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["skipped"], 3)

        with Session(self.engine) as session:
            batched = session.exec(select(AccountActionTask).where(
                AccountActionTask.batch_id == result["batch_id"])).all()
            self.assertEqual(len(batched), 1)
            self.assertEqual(batched[0].action, "follow")
            self.assertEqual(batched[0].target_sec_uid, "alice")
            self.assertGreaterEqual(batched[0].min_gap_seconds, 75)
            self.assertLessEqual(batched[0].min_gap_seconds, 105)
            batch = session.get(XRelationshipBatch, result["batch_id"])
            self.assertEqual(batch.action, "follow")
            self.assertEqual(batch.total_count, 1)
            self.assertEqual(batch.skipped_count, 3)

    def test_followback_target_count_applies_after_filtering_invalid_and_duplicate_targets(self):
        with Session(self.engine) as session:
            edges = []
            for name in ("alice", "bob", "carol", "dave"):
                edge = FollowEdge(
                    platform="x", account_id=self.account_id,
                    direction="fan", uid=name, sec_uid=name,
                    nickname=name.title(), is_following=False)
                session.add(edge)
                edges.append(edge)
            session.commit()
            for edge in edges:
                session.refresh(edge)
            session.add(AccountActionTask(
                platform="x", account_id=self.account_id,
                action="follow", target_uid="alice", target_sec_uid="alice",
                target_nick="Alice", status="pending"))
            session.commit()
            edge_ids = [edge.id for edge in edges]

        result = asyncio.run(main.create_account_actions_batch(main.BatchActionIn(
            account_id=self.account_id,
            action="follow",
            edge_ids=edge_ids,
            target_count=2,
        )))
        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["queued"], 2)
        self.assertEqual(result["skipped"], 1)

        with Session(self.engine) as session:
            batched = session.exec(select(AccountActionTask).where(
                AccountActionTask.batch_id == result["batch_id"])).all()
            self.assertEqual(
                [row.target_sec_uid for row in batched],
                ["bob", "carol"],
            )
            batch = session.get(XRelationshipBatch, result["batch_id"])
            self.assertEqual(batch.requested_count, 2)
            self.assertEqual(batch.total_count, 2)

    def test_batch_controls_pause_resume_and_cancel_only_pending(self):
        with Session(self.engine) as session:
            edges = []
            for name in ("alice", "bob", "carol"):
                edge = FollowEdge(
                    platform="x", account_id=self.account_id,
                    direction="following", uid=name, sec_uid=name,
                    nickname=name.title(), is_following=True)
                session.add(edge)
                edges.append(edge)
            session.commit()
            for edge in edges:
                session.refresh(edge)
            edge_ids = [edge.id for edge in edges]

        created = asyncio.run(main.create_account_actions_batch(main.BatchActionIn(
            account_id=self.account_id, action="unfollow", edge_ids=edge_ids)))
        batch_id = created["batch_id"]
        self.assertEqual(created["queued"], 3)

        paused = asyncio.run(main.pause_x_relationship_batch(batch_id))
        self.assertEqual(paused["batch"]["status"], "paused")

        resumed = asyncio.run(main.resume_x_relationship_batch(batch_id))
        self.assertEqual(resumed["batch"]["status"], "active")

        with Session(self.engine) as session:
            task = session.exec(select(AccountActionTask).where(
                AccountActionTask.batch_id == batch_id)).first()
            task.status = "done"
            session.add(task)
            session.commit()

        canceled = asyncio.run(main.cancel_x_relationship_batch(batch_id))
        self.assertEqual(canceled["canceled"], 2)
        self.assertEqual(canceled["batch"]["status"], "canceled")
        with Session(self.engine) as session:
            states = [row.status for row in session.exec(select(AccountActionTask).where(
                AccountActionTask.batch_id == batch_id)).all()]
            self.assertEqual(states.count("done"), 1)
            self.assertEqual(states.count("canceled"), 2)

    def test_batch_anomaly_classifier_pauses_uncertain_and_platform_risk(self):
        for kwargs, signal in (
            ({"uncertain": True}, "uncertain"),
            ({"error": "CAPTCHA required"}, "captcha"),
            ({"error": "HTTP 429 Too Many Requests"}, "rate_limit"),
            ({"error": "login required"}, "auth"),
            ({"error": "restricted account"}, "restriction"),
            ({"error": "risk response", "failure_category": "risk",
              "failure_signal": "platform_risk"}, "platform_risk"),
        ):
            should_pause, reason, got_signal = should_pause_relationship_batch(**kwargs)
            self.assertTrue(should_pause)
            self.assertTrue(reason)
            self.assertEqual(got_signal, signal)

        should_pause, _, _ = should_pause_relationship_batch(
            error="temporary network timeout", failure_category="network")
        self.assertFalse(should_pause)

    def test_batch_unfollow_over_500_is_accepted_and_chunked_server_side(self):
        accepted = asyncio.run(main.create_account_actions_batch(main.BatchActionIn(
            account_id=self.account_id,
            action="unfollow",
            edge_ids=list(range(1, 551)),
        )))
        self.assertEqual(accepted["queued"], 0)
        self.assertEqual(accepted["skipped"], 550)
        self.assertEqual(accepted["chunk_size"], 500)
        self.assertEqual(accepted["chunks"], 2)


if __name__ == "__main__":
    unittest.main()
