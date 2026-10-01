"""数据库初始化（SQLite + SQLAlchemy）。

为 Hackathon 选择 SQLite，零运维。文件位置：backend/sage.db

包含一个轻量级"自动加列"迁移：启动时若发现表里缺新增列，
直接 ALTER TABLE ADD COLUMN 补上。这样改 schema 不用删 db。
注意：只支持加列，不支持改类型/删列。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

# 数据库文件路径：backend/sage.db
DB_PATH = Path(__file__).resolve().parent.parent / "sage.db"
DATABASE_URL = os.environ.get("SAGE_DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite:") else {},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入用的 DB Session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sqlite_column_type(col) -> str:
    """SQLAlchemy Column → SQLite 列类型字符串。"""
    try:
        return col.type.compile(dialect=engine.dialect)
    except Exception:  # noqa: BLE001
        # 兜底：常见类型映射
        return "TEXT"


def _auto_add_missing_columns() -> None:
    """对每张已存在的表，比对 metadata 与实际列，缺什么 ALTER TABLE ADD COLUMN 加上。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                # 表不存在，create_all 会处理
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = _sqlite_column_type(col)
                # SQLite 不允许 ADD COLUMN 带 NOT NULL 又没默认值；
                # 我们的所有新列都是 nullable 或带 default，所以直接加
                nullable_clause = "" if col.nullable else " NOT NULL"
                default_clause = ""
                if col.server_default is not None:
                    default_expr = col.server_default.arg
                    if hasattr(default_expr, "compile"):
                        default_expr = default_expr.compile(dialect=engine.dialect)
                    default_clause = f" DEFAULT {default_expr}"
                stmt = (f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" '
                        f'{col_type}{default_clause}{nullable_clause}')
                logger.warning("[auto-migrate] %s", stmt)
                try:
                    conn.execute(text(stmt))
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"数据库自动加列失败：{table_name}.{col.name}；请先备份数据库并检查迁移"
                    ) from exc


def init_db() -> None:
    """初始化所有表 + 自动加缺失的列。"""
    # 显式 import 让模型注册到 Base.metadata
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # 在 create_all 之后再扫一遍：处理"表存在但少列"场景
    _auto_add_missing_columns()
    from app.services.profile_scope import service_profile_id
    from app.services.taxonomy import list_services
    with engine.begin() as conn:
        for service_id in {item["id"] for item in list_services()}:
            profile_id = service_profile_id(service_id)
            if not profile_id:
                continue  # Ambiguous legacy service: never guess a Profile.
            for table in ("assessments", "question_sessions", "ticket_sessions"):
                conn.execute(text(f"UPDATE {table} SET profile_id = :profile "
                                  "WHERE service_id = :service AND (profile_id IS NULL OR profile_id = '')"),
                             {"profile": profile_id, "service": service_id})
        import json
        scenario_dir = Path(__file__).resolve().parents[2] / "data" / "scenarios"
        for path in scenario_dir.glob("*.json"):
            scenario = json.loads(path.read_text(encoding="utf-8"))
            profile_id = service_profile_id(scenario.get("service_id", ""))
            if profile_id:
                conn.execute(text("UPDATE practice_runs SET profile_id = :profile "
                                  "WHERE scenario_id = :scenario AND (profile_id IS NULL OR profile_id = '')"),
                             {"profile": profile_id, "scenario": scenario.get("id", path.stem)})
    with engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_session_id ON assessments (session_id)"))
        for table in ("assessments", "question_sessions", "ticket_sessions", "practice_runs", "background_tasks"):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_profile "
                              f"ON {table} (user_id, profile_id)"))
