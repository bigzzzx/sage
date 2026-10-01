"""SQLAlchemy ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


class Assessment(Base):
    """一次测评记录。"""

    __tablename__ = "assessments"
    __table_args__ = (Index("uq_assessment_session_id", "session_id", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="demo_user")
    profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="pre")  # pre / post
    record_origin: Mapped[str | None] = mapped_column(String(16), nullable=True, default="user")  # user / agent_test
    service_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
    plan_review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Agent 化：诊断盲区列表 + 每步推理 trace
    diagnosis: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    agent_trace: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    rag_sources: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

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
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuthThrottle(Base):
    """Persistent failed-login counter keyed by a hash of username and peer address."""

    __tablename__ = "auth_throttles"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started: Mapped[float] = mapped_column(Float, default=0.0)
    blocked_until: Mapped[float] = mapped_column(Float, default=0.0)


class AdminAudit(Base):
    """Minimal append-only record of privileged account changes."""

    __tablename__ = "admin_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class KnowledgeEntry(Base):
    """Reviewed knowledge contribution; only published rows enter RAG."""

    __tablename__ = "knowledge_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(String(32), index=True)
    service_id: Mapped[str] = mapped_column(String(32), index=True)
    capability_id: Mapped[str] = mapped_column(String(64), default="")
    source_type: Mapped[str] = mapped_column(String(20))  # case / official_doc
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_ticket_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    replaces_entry_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    index_status: Mapped[str] = mapped_column(String(20), default="not_indexed")
    created_by: Mapped[str] = mapped_column(String(64), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class TrainingEnrollment(Base):
    """An explicit profile-specific training roster, independent of login profile."""

    __tablename__ = "training_enrollments"
    __table_args__ = (Index("uq_training_enrollment", "user_id", "profile_id", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class QuestionSession(Base):
    """Server-side question/answer snapshot bound to its owner."""

    __tablename__ = "question_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    service_id: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    study_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="pre")
    prev_assessment_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    blueprint: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BackgroundTask(Base):
    """Durable status/result for one asynchronous assessment operation."""

    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    job_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_usage: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class PracticeRun(Base):
    """One user's evidence trail and submitted diagnosis for a training case."""

    __tablename__ = "practice_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    inspected_tools: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class TicketSession(Base):
    """A simulated customer ticket; hidden case facts never leave the server before grading."""

    __tablename__ = "ticket_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    service_id: Mapped[str] = mapped_column(String(32), default="glue")
    category: Mapped[str] = mapped_column(String(32))
    persona_id: Mapped[str] = mapped_column(String(32))
    customer_name: Mapped[str] = mapped_column(String(80))
    case_id: Mapped[str] = mapped_column(String(64))
    case_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_id: Mapped[str] = mapped_column(String(128))
    impact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cross_service: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    conversation_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    revealed_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")
    final_answer: Mapped[str] = mapped_column(Text, default="")
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class LearningTaskProgress(Base):
    """Self-reported deliverable for one task in a persisted assessment plan."""

    __tablename__ = "learning_task_progress"
    __table_args__ = (Index("uq_learning_task", "assessment_id", "week_index", "task_index", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    assessment_id: Mapped[str] = mapped_column(String(32), index=True)
    week_index: Mapped[int] = mapped_column()
    task_index: Mapped[int] = mapped_column()
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class QualityFeedback(Base):
    """User correction request; the original grading or ticket record stays immutable."""

    __tablename__ = "quality_feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(String(32), index=True)
    record_type: Mapped[str] = mapped_column(String(16))
    record_id: Mapped[str] = mapped_column(String(32), index=True)
    question_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    original_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class TrainingAssignment(Base):
    """A manager-assigned, profile-scoped exercise with a fixed comparison blueprint."""

    __tablename__ = "training_assignments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(String(32), index=True)
    service_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    capability_id: Mapped[str] = mapped_column(String(64), default="")
    question_count: Mapped[int] = mapped_column(Integer, default=12)
    difficulty_profile: Mapped[str] = mapped_column(String(16), default="balanced")
    focus: Mapped[str] = mapped_column(String(20), default="comprehensive", server_default="comprehensive")
    scoring_version: Mapped[str] = mapped_column(String(24), default="assessment_v3", server_default="assessment_v3")
    note: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
