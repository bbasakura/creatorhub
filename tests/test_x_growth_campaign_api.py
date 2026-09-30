import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.db as db
import app.api.x as x_api
from app.models import AccountActionTask, DouyinAccount
from app.services.x_growth_campaign import (
    growth_task_metadata,
    load_growth_campaign,
)


class _Risk:
    def preflight(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=True, reason="")
    def record_success(self, *_args, **_kwargs):
        return None
    def record_failure(self, *_args, **_kwargs):
        return SimpleNamespace()


class _Browser:
    def identity_for(self, account):
        return SimpleNamespace(account_id=account.id)


class _Engine:
    def __init__(self):
        self.risk = _Risk()
        self.cfg = SimpleNamespace(
            engine=SimpleNamespace(
                action_min_gap_seconds=90,
                action_hourly_cap_per_account=6,
                action_daily_cap_per_account=20,
            ),
            risk_control=SimpleNamespace(
                social_min_gap_seconds=900,
                social_hourly_cap=2,
                social_daily_cap=8,
            ),
        )

    @asynccontextmanager
    async def operation_guard(self, *_args, **_kwargs):
        yield None


def _seed_x_account() -> int:
    with db.get_session() as session:
        account = DouyinAccount(
            platform="x",
            nickname="@sakurakk730",
            sec_uid="sakurakk730",
            status="active",
            storage_state='{"cookies":[{"name":"auth_token","value":"test"}]}',
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return int(account.id)


def test_growth_start_validates_login_and_persists_campaign():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "growth-api.db"))
        try:
            account_id = _seed_x_account()
            engine = _Engine()
            with patch.object(x_api, "_runtime", return_value=(_Browser(), engine)), \
                 patch.object(x_api, "fetch_x_self_profile", AsyncMock(return_value={"handle": "sakurakk730"})):
                result = asyncio.run(x_api.growth_campaign_start(
                    x_api.XGrowthCampaignIn(account_id=account_id, target_count=7)))
            assert result["ok"] is True
            assert result["state"]["enabled"] is True
            assert result["state"]["status"] == "running"
            assert result["state"]["target_count"] == 7
            assert result["limits"]["target_interval_seconds"] == 60
            assert result["limits"]["interval_min_seconds"] == 50
            assert result["limits"]["interval_max_seconds"] == 70
            assert "risk_social_min_gap_seconds" not in result["limits"]
            assert load_growth_campaign(account_id)["enabled"] is True
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_growth_start_returns_exact_login_message_when_session_is_logged_out():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "growth-login.db"))
        try:
            account_id = _seed_x_account()
            engine = _Engine()
            with patch.object(x_api, "_runtime", return_value=(_Browser(), engine)), \
                 patch.object(
                     x_api, "fetch_x_self_profile",
                     AsyncMock(side_effect=RuntimeError("logged_out:X 登录态已失效，请重新登录"))):
                try:
                    asyncio.run(x_api.growth_campaign_start(
                        x_api.XGrowthCampaignIn(account_id=account_id)))
                except x_api.HTTPException as exc:
                    assert exc.status_code == 400
                    assert exc.detail == "X登录态失效，请在面板手动登录后重试"
                else:
                    raise AssertionError("expected HTTPException")
            assert load_growth_campaign(account_id)["enabled"] is False
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous


def test_growth_stop_cancels_only_pending_campaign_follow_tasks():
    previous = db._engine
    with tempfile.TemporaryDirectory() as directory:
        db.init_db(str(Path(directory) / "growth-stop.db"))
        try:
            account_id = _seed_x_account()
            with db.get_session() as session:
                growth = AccountActionTask(
                    platform="x", account_id=account_id, action="follow",
                    target_uid="growth_target", target_nick="growth",
                    content=growth_task_metadata(source="关键词:#蓝V互关"),
                    status="pending",
                )
                manual = AccountActionTask(
                    platform="x", account_id=account_id, action="follow",
                    target_uid="manual_target", target_nick="manual",
                    content="", status="pending",
                )
                session.add(growth)
                session.add(manual)
                session.commit()
                session.refresh(growth)
                session.refresh(manual)
                growth_id, manual_id = growth.id, manual.id
            engine = _Engine()
            with patch.object(x_api, "_runtime", return_value=(_Browser(), engine)):
                result = asyncio.run(x_api.growth_campaign_stop(
                    x_api.XGrowthCampaignIn(account_id=account_id)))
            assert result["canceled_pending"] == 1
            with db.get_session() as session:
                assert session.get(AccountActionTask, growth_id).status == "canceled"
                assert session.get(AccountActionTask, manual_id).status == "pending"
        finally:
            if db._engine is not None:
                db._engine.dispose()
            db._engine = previous
