from __future__ import annotations

from datetime import datetime

from sqlmodel import select

from ..db import get_session
from ..models import XOpsSettings

MIN_TARGET_COUNT = 1
MAX_TARGET_COUNT = 10000
DEFAULT_TARGET_COUNT = 100


def normalize_x_ops_target_count(value: int | str | None) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_TARGET_COUNT)
    except (TypeError, ValueError):
        parsed = DEFAULT_TARGET_COUNT
    return max(MIN_TARGET_COUNT, min(MAX_TARGET_COUNT, parsed))


def get_x_ops_target_count(account_id: int) -> int:
    with get_session() as session:
        row = session.exec(select(XOpsSettings).where(
            XOpsSettings.account_id == int(account_id)
        )).first()
        return normalize_x_ops_target_count(
            row.target_count if row is not None else DEFAULT_TARGET_COUNT)


def save_x_ops_target_count(account_id: int, target_count: int) -> int:
    value = normalize_x_ops_target_count(target_count)
    with get_session() as session:
        row = session.exec(select(XOpsSettings).where(
            XOpsSettings.account_id == int(account_id)
        )).first()
        if row is None:
            row = XOpsSettings(account_id=int(account_id), target_count=value)
        else:
            row.target_count = value
            row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    return value
