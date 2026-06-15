"""SQLAlchemy ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


class Assessment(Base):
    """一次测评记录。"""

    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="demo_user")
    kind: Mapped[str] = mapped_column(String(16), default="pre")  # pre / post
    service_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    prev_assessment_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    overall_level: Mapped[str] = mapped_column(String(8), default="L1")
    choice_score: Mapped[str] = mapped_column(String(16), default="-")
    overall_avg: Mapped[float] = mapped_column(Float, default=0.0)

    # JSON 大字段：完整保留题目、答案、评分、雷达、计划，方便后续分析
    questions_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[list] = mapped_column(JSON, default=list)
    question_results: Mapped[list] = mapped_column(JSON, default=list)
    radar: Mapped[list] = mapped_column(JSON, default=list)
    learning_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Agent 化：诊断盲区列表 + 每步推理 trace
    diagnosis: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    agent_trace: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class User(Base):
    """用户表。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="member")  # member / manager
    current_profile: Mapped[str] = mapped_column(String(32), default="big_data")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
