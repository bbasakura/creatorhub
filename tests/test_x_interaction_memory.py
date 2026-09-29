import tempfile
from datetime import datetime
from pathlib import Path

from app import db
from app.models import CommentTask
from app.services.x_interaction_memory import load_x_interaction_memory


def test_memory_uses_only_successful_same_account_same_handle_replies():
    original = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "memory.db"))
        try:
            with db.get_session() as session:
                session.add(CommentTask(
                    platform="x", account_id=8, status="done",
                    aweme_id="1", target_nick="Tester",
                    target_text="之前聊过幂等", content="提交边界要单独处理",
                    done_at=datetime(2026, 9, 28, 10, 0, 0)))
                session.add(CommentTask(
                    platform="x", account_id=8, status="draft",
                    aweme_id="2", target_nick="tester",
                    target_text="未发送草稿", content="不能算历史互动"))
                session.add(CommentTask(
                    platform="x", account_id=9, status="done",
                    aweme_id="3", target_nick="tester", content="另一个账号"))
                session.commit()
            memory = load_x_interaction_memory(8, "@TESTER")
            assert memory.successful_replies == 1
            assert memory.recent[0]["tweet_id"] == "1"
            prompt = memory.prompt_context()
            assert "历史成功互动 1 次" in prompt
            assert "提交边界要单独处理" in prompt
            assert "未发送草稿" not in prompt
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = original


def test_empty_handle_returns_empty_memory_without_db_query():
    memory = load_x_interaction_memory(8, "")
    assert memory.successful_replies == 0
    assert memory.prompt_context() == ""
