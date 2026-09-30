import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app.db as db
import app.main as main
from app.models import (
    AccountActionTask,
    CommentTask,
    ContentRecord,
    DouyinAccount,
    KeywordCollectionContent,
    KeywordCollectionJob,
    MonitorTarget,
    PublishTask,
    XRelationshipBatch,
)


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.previous_engine = db._engine
        self.tmp = tempfile.TemporaryDirectory()
        db.init_db(str(Path(self.tmp.name) / "task-queue.db"))
        now = datetime.utcnow()
        with db.get_session() as session:
            account = DouyinAccount(platform="douyin", nickname="队列样本账号")
            session.add(account)
            session.commit()
            session.refresh(account)
            self.account_id = account.id

            target = MonitorTarget(
                platform="douyin", account_id=account.id,
                nickname="监控目标", sec_uid="target-user")
            session.add(target)
            session.commit()
            session.refresh(target)

            job = KeywordCollectionJob(
                platform="douyin", account_id=account.id,
                keywords='["防晒霜"]', status="pending",
                current_step="等待账号读取冷却", blocked_reason="账号处于风险冷却期",
                blocked_signal="cooldown", next_allowed_at=now + timedelta(minutes=20))
            session.add(job)
            session.commit()
            session.refresh(job)

            session.add(PublishTask(
                platform="douyin", account_id=account.id, title="夏日防晒指南",
                status="pending", scheduled_at=now + timedelta(minutes=10)))
            session.add(CommentTask(
                platform="douyin", account_id=account.id, content="感谢分享",
                aweme_id="note-1", status="doing"))
            session.add(AccountActionTask(
                platform="douyin", account_id=account.id, action="follow",
                target_nick="目标作者", status="failed", error="操作间隔不足"))
            session.add(ContentRecord(
                platform="douyin", target_id=target.id, aweme_id="work-1",
                desc="监控下载样本", download_status="pending"))
            session.add(KeywordCollectionContent(
                job_id=job.id, platform="douyin", keyword="防晒霜",
                aweme_id="work-2", desc="采集下载样本", download_status="downloading"))
            session.add(PublishTask(
                platform="douyin", account_id=account.id, title="已经发布",
                status="done", done_at=now))
            session.commit()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = self.previous_engine
        self.tmp.cleanup()

    def query(self, **overrides):
        params = {
            "platform": "douyin", "queue_type": "", "state": "active",
            "q": "", "page": 1, "page_size": 20,
        }
        params.update(overrides)
        return asyncio.run(main.list_task_queue(**params))

    def test_active_queue_unifies_all_persistent_sources(self):
        result = self.query()

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["summary"]["active"], 5)
        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(result["summary"]["pending"], 2)
        self.assertEqual(result["summary"]["running"], 2)
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual({item["queue_type"] for item in result["items"]}, {
            "collections", "publishes", "comments",
            "monitor_downloads", "collection_downloads",
        })

    def test_filters_blocked_type_platform_and_search(self):
        blocked = self.query(state="blocked")
        self.assertEqual(blocked["total"], 1)
        self.assertEqual(blocked["items"][0]["blocked_signal"], "cooldown")
        self.assertIn("风险冷却", blocked["items"][0]["blocked_reason"])

        publishes = self.query(queue_type="publishes")
        self.assertEqual(publishes["total"], 1)
        self.assertEqual(publishes["items"][0]["title"], "夏日防晒指南")

        searched = self.query(q="队列样本账号")
        self.assertEqual(searched["total"], 5)
        self.assertEqual(self.query(platform="xhs")["total"], 0)

    def test_completed_history_and_pagination(self):
        completed = self.query(state="completed")
        self.assertEqual(completed["total"], 1)
        self.assertEqual(completed["items"][0]["state"], "completed")

        page = self.query(page=2, page_size=2)
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["pages"], 3)
        self.assertEqual(len(page["items"]), 2)

    def test_rejects_unknown_filters(self):
        with self.assertRaises(main.HTTPException):
            self.query(queue_type="not-a-queue")
        with self.assertRaises(main.HTTPException):
            self.query(state="not-a-state")
        with self.assertRaises(main.HTTPException):
            self.query(platform="x", state="all", x_action="not-an-action")
        with self.assertRaises(main.HTTPException):
            self.query(platform="x", state="all", x_status="not-a-status")

    def test_x_queue_uses_business_actions_and_independent_statuses(self):
        now = datetime.utcnow()
        with db.get_session() as session:
            account = DouyinAccount(platform="x", nickname="X 队列账号")
            session.add(account)
            session.commit()
            session.refresh(account)

            follow_batch = XRelationshipBatch(
                account_id=account.id, action="follow", status="active",
                requested_count=1, total_count=1)
            unfollow_batch = XRelationshipBatch(
                account_id=account.id, action="unfollow", status="active",
                requested_count=1, total_count=1)
            session.add(follow_batch)
            session.add(unfollow_batch)
            session.commit()
            session.refresh(follow_batch)
            session.refresh(unfollow_batch)

            session.add(AccountActionTask(
                platform="x", account_id=account.id, action="follow",
                target_nick="浇友目标", status="pending",
                content='{"campaign":"jiaoyou","source":"test","require_verified":true}'))
            session.add(AccountActionTask(
                platform="x", account_id=account.id, batch_id=follow_batch.id,
                action="follow", target_nick="回关目标", status="doing"))
            session.add(AccountActionTask(
                platform="x", account_id=account.id, batch_id=unfollow_batch.id,
                action="unfollow", target_nick="取关目标", status="pending",
                next_allowed_at=now + timedelta(minutes=5)))
            session.add(CommentTask(
                platform="x", account_id=account.id, content="催关",
                aweme_id="remind-1", xsec_token="x_remind:one", status="uncertain"))
            session.add(CommentTask(
                platform="x", account_id=account.id, content="串门",
                aweme_id="visit-1", xsec_token="x_visit:one", status="failed"))
            session.add(PublishTask(
                platform="x", account_id=account.id, title="X 草稿",
                status="draft", source_intent_key="x-draft:test:oneclick-1"))
            session.commit()

        all_rows = self.query(platform="x", state="all", x_status="all")
        self.assertEqual(all_rows["total"], 6)
        self.assertEqual({
            item["x_action"] for item in all_rows["items"]
        }, {"growth", "followback", "unfollow", "remind", "visit", "post"})
        self.assertEqual(all_rows["x_summary"]["running"], 1)
        self.assertEqual(all_rows["x_summary"]["cooldown"], 1)
        self.assertEqual(all_rows["x_summary"]["draft"], 1)
        self.assertEqual(all_rows["x_summary"]["uncertain"], 1)
        self.assertEqual(all_rows["x_summary"]["failed"], 1)

        growth = self.query(
            platform="x", state="all", x_status="all", x_action="growth")
        self.assertEqual(growth["total"], 1)
        self.assertEqual(growth["items"][0]["queue_label"], "一键浇友")

        remind = self.query(
            platform="x", state="all", x_status="uncertain", x_action="remind")
        self.assertEqual(remind["total"], 1)
        self.assertEqual(remind["items"][0]["queue_label"], "一键催关")
        self.assertEqual(remind["items"][0]["x_status"], "uncertain")

        cooldown = self.query(
            platform="x", state="all", x_status="cooldown", x_action="unfollow")
        self.assertEqual(cooldown["total"], 1)
        self.assertEqual(cooldown["items"][0]["queue_label"], "一键取关")

    def test_bulk_cancel_ui_contract(self):
        index = Path("app/web/index.html").read_text(encoding="utf-8")
        js = Path("app/web/app.js").read_text(encoding="utf-8")
        self.assertIn('id="queue-selall"', index)
        self.assertIn('id="queue-bulk-cancel"', index)
        self.assertIn("cancelSelectedTaskQueue", js)
        self.assertIn('/api/task-queue/batch/cancel', js)

    def test_bulk_cancel_reuses_per_task_cancel_state_machine(self):
        with db.get_session() as session:
            comment = CommentTask(
                platform="douyin", account_id=self.account_id,
                content="待取消评论", aweme_id="cancel-comment", status="pending")
            action = AccountActionTask(
                platform="douyin", account_id=self.account_id,
                action="follow", target_nick="待取消账号", status="pending")
            session.add(comment); session.add(action); session.commit()
            session.refresh(comment); session.refresh(action)
            comment_id, action_id = comment.id, action.id

        result = asyncio.run(main.cancel_task_queue_batch(
            main.TaskQueueBulkCancelIn(items=[
                main.TaskQueueBulkItemIn(queue_type="comments", id=comment_id),
                main.TaskQueueBulkItemIn(queue_type="actions", id=action_id),
            ])))
        self.assertEqual(result["canceled"], 2)
        self.assertEqual(result["skipped"], 0)
        with db.get_session() as session:
            self.assertEqual(session.get(CommentTask, comment_id).status, "canceled")
            self.assertEqual(session.get(AccountActionTask, action_id).status, "canceled")


if __name__ == "__main__":
    unittest.main()
