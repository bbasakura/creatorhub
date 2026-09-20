"""数据库初始化与会话。含 SQLite 轻量自动迁移(为已有表补缺失列)。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

_engine = None


def _backup_before_migration(db_path: str):
    path = Path(db_path)
    if not path.is_file() or not path.stat().st_size:
        return
    with closing(sqlite3.connect(str(path))) as source:
        has_versions = source.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migration'").fetchone()
        if has_versions and source.execute('SELECT 1 FROM schema_migration WHERE version=1').fetchone():
            return
        backup_dir = path.parent / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f'{path.stem}-before-v1-{datetime.now():%Y%m%d-%H%M%S-%f}.db'
        with closing(sqlite3.connect(str(backup))) as target:
            source.backup(target)


def _versioned_migrations(engine):
    with engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS schema_migration (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)'))
        if c.execute(text('SELECT 1 FROM schema_migration WHERE version=1')).first():
            return
        duplicate = c.execute(text("""SELECT account_id, source_content_id, COUNT(*) FROM publishtask
            WHERE source_platform='d2y' AND source_content_id IS NOT NULL AND source_intent_key IS NULL
            GROUP BY account_id, source_content_id, operation HAVING COUNT(*)>1 LIMIT 1""")).first()
        if duplicate:
            raise RuntimeError('Duplicate legacy D2Y intents require explicit reconciliation before migration')
        c.execute(text("""UPDATE publishtask SET source_intent_key=
            'd2y:' || account_id || ':' || source_content_id || ':' || operation || :suffix
            WHERE source_platform='d2y' AND source_content_id IS NOT NULL AND source_intent_key IS NULL"""), {'suffix': ':initial'})
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_publishtask_content_fingerprint ON publishtask(content_fingerprint)'))
        c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_publishtask_source_intent_key ON publishtask(source_intent_key)'))
        c.execute(text("INSERT INTO schema_migration VALUES (1, :now)"), {'now':datetime.utcnow().isoformat()})


def _auto_migrate(engine):
    """为已存在的表补上模型里新增的列(SQLite 友好,仅 ADD COLUMN)。"""
    insp = inspect(engine)
    for table in SQLModel.metadata.tables.values():
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(engine.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
            # 模型若给了标量默认值,作为 SQL DEFAULT 写入 —— SQLite 会用它回填已有行,
            # 避免新列在旧数据上为 NULL(例如 platform 列需回填为 'douyin')。
            scalar = (getattr(col.default, "arg", None)
                      if col.default is not None and getattr(col.default, "is_scalar", False)
                      else None)
            if isinstance(scalar, bool):
                ddl += f" DEFAULT {1 if scalar else 0}"
            elif isinstance(scalar, str):
                ddl += " DEFAULT '" + scalar.replace("'", "''") + "'"
            elif isinstance(scalar, (int, float)):
                ddl += f" DEFAULT {scalar}"
            elif not col.nullable:
                ddl += " DEFAULT ''"
            with engine.begin() as conn:
                conn.execute(text(ddl))


def init_db(db_path: str):
    global _engine
    _backup_before_migration(db_path)
    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(_engine)
    _auto_migrate(_engine)
    _versioned_migrations(_engine)
    if inspect(_engine).has_table("publishtask"):
        with _engine.begin() as conn:
            conn.execute(text("UPDATE publishtask SET operation='draft' WHERE platform='wechat_mp' AND operation='publish'"))
    return _engine


def get_session() -> Session:
    assert _engine is not None, "init_db() 未调用"
    return Session(_engine)
