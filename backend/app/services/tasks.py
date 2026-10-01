"""Persist named assessment jobs before executing them in a bounded local pool.

Saved jobs are replayed after a single-process restart. Legacy closure jobs
remain non-replayable and are marked failed when interrupted.
"""
from __future__ import annotations

import logging
import threading
import uuid
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from fastapi.encoders import jsonable_encoder
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import BackgroundTask
from app.services.profile_scope import current_profile_id, record_profile_id, service_profile_id

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sage-job")
_scheduled: set[str] = set()
_schedule_lock = threading.Lock()


def _public_error(exc: Exception) -> str:
    """Give an actionable category without returning provider internals or user data."""
    if isinstance(exc, AuthenticationError):
        return "模型认证失败，请管理员检查服务端密钥配置"
    if isinstance(exc, RateLimitError):
        return "模型服务已限流，请稍后重试"
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return "无法连接模型服务，请检查网络或模型地址后重试"
    from fastapi import HTTPException
    if isinstance(exc, HTTPException) and isinstance(exc.detail, str) and exc.detail.startswith(("工单", "模拟工单", "该服务", "请先与客户", "处理方案")):
        return exc.detail[:160]
    if isinstance(exc, ValueError):
        message = str(exc)
        if message.startswith(("题目", "出题", "AI 评分", "测评", "选择题", "开放题", "生成题目")):
            return message[:120]
    return "任务执行失败，请重试；已完成的成绩不会被覆盖"


def create_task(fn: Callable[[], Any], *, user_id: str) -> str:
    task_id = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(BackgroundTask(id=task_id, user_id=user_id,
                              profile_id=current_profile_id(db, user_id), status="pending"))
        db.commit()

    def run() -> None:
        with SessionLocal() as db:
            task = db.get(BackgroundTask, task_id)
            task.status = "running"
            db.commit()
        from app.services.llm import capture_llm_usage
        started = time.perf_counter()
        with capture_llm_usage() as usage:
            try:
                result = jsonable_encoder(fn())
            except Exception as exc:
                logger.exception("Task %s failed", task_id)
                with SessionLocal() as db:
                    task = db.get(BackgroundTask, task_id)
                    task.status = "error"
                    task.error = _public_error(exc)
                    task.runtime_ms = round((time.perf_counter() - started) * 1000)
                    task.llm_usage = list(usage)
                    db.commit()
                return
        with SessionLocal() as db:
            task = db.get(BackgroundTask, task_id)
            task.status = "done"
            task.result = result
            task.runtime_ms = round((time.perf_counter() - started) * 1000)
            task.llm_usage = list(usage)
            db.commit()

    threading.Thread(target=run, daemon=True).start()
    return task_id


def get_task(task_id: str, *, user_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        if not task or task.user_id != user_id:
            return None
        profile_id = task.profile_id or (task.payload or {}).get("profile_id")
        if not profile_id:
            payload = task.payload or {}
            profile_id = service_profile_id(payload.get("service_id", ""))
            if not profile_id:
                from app.models import Assessment, QuestionSession, TicketSession
                row = (db.get(QuestionSession, payload["session_id"]) if payload.get("session_id") else
                       db.get(Assessment, payload["prev_assessment_id"]) if payload.get("prev_assessment_id") else
                       db.get(Assessment, payload["assessment_id"]) if payload.get("assessment_id") else
                       db.get(TicketSession, payload["ticket_id"]) if payload.get("ticket_id") else None)
                profile_id = record_profile_id(row) if row else None
        if profile_id != current_profile_id(db, user_id):
            return None
        return {"status": task.status, "result": task.result, "error": task.error}


def _execute_job(kind: str, payload: dict, user_id: str) -> Any:
    """Only named, validated application operations may be replayed after restart."""
    if kind == "ticket_create":
        from app.api.tickets import StartTicketRequest, create_ticket
        return create_ticket(StartTicketRequest(**{k: v for k, v in payload.items() if k not in {"ticket_id", "profile_id"}}),
                             {"uid": user_id}, ticket_id=payload["ticket_id"], profile_id=payload.get("profile_id"))
    if kind == "ticket_finish":
        from app.api.tickets import FinishTicketRequest, _finish_ticket
        return _finish_ticket(payload["ticket_id"], FinishTicketRequest(final_answer=payload["final_answer"]),
                              {"uid": user_id}, profile_id=payload.get("profile_id"))
    if kind == "generate":
        from app.services.question_gen import generate_questions, public_questions
        session_id, questions = generate_questions(
            service_id=payload["service_id"],
            capability_ids=payload["capability_ids"] or None,
            question_count=payload.get("question_count", 9),
            difficulty_profile=payload.get("difficulty_profile", "balanced"),
            focus=payload.get("focus", "comprehensive"), user_id=user_id,
            model_id=payload["model_id"],
            study_days=payload.get("study_days", 5),
            minutes_per_day=payload.get("minutes_per_day", 90),
            session_id=payload.get("generated_session_id"), profile_id=payload.get("profile_id"))
        return {"session_id": session_id, "questions": public_questions(questions)}
    if kind == "post_generate":
        from app.api.assessment import _do_post_test_generate
        return _do_post_test_generate(payload["prev_assessment_id"], user_id,
                                      payload["model_id"],
                                      payload.get("generated_session_id"))
    if kind == "retry_learning":
        from app.services.assessment import retry_learning
        return retry_learning(payload["assessment_id"], user_id).model_dump()
    if kind in {"submit", "post_submit"}:
        from app.schemas.assessment import AnswerItem
        from app.services.assessment import run_assessment
        result = run_assessment(
            user_id=user_id,
            answer_items=[AnswerItem(**item) for item in payload["answers"]],
            session_id=payload["session_id"],
            kind="pre" if kind == "submit" else "post",
            prev_assessment_id=payload.get("prev_assessment_id"))
        return result.model_dump()
    raise ValueError("未知的后台任务类型")


def _run_persisted(task_id: str) -> None:
    from sqlalchemy import update
    try:
        with SessionLocal() as db:
            claimed = db.execute(
                update(BackgroundTask).where(BackgroundTask.id == task_id,
                                             BackgroundTask.status == "pending")
                .values(status="running"))
            db.commit()
            if claimed.rowcount != 1:
                return
            task = db.get(BackgroundTask, task_id)
            kind, payload, user_id = task.job_kind, task.payload, task.user_id
        from app.services.llm import capture_llm_usage
        started = time.perf_counter()
        with capture_llm_usage() as usage:
            try:
                result = jsonable_encoder(_execute_job(kind, payload, user_id))
            except Exception as exc:
                logger.exception("Persisted task %s failed", task_id)
                with SessionLocal() as db:
                    task = db.get(BackgroundTask, task_id)
                    task.status, task.error = "error", _public_error(exc)
                    task.runtime_ms = round((time.perf_counter() - started) * 1000)
                    task.llm_usage = list(usage)
                    db.commit()
                return
        with SessionLocal() as db:
            task = db.get(BackgroundTask, task_id)
            task.status, task.result, task.error = "done", result, None
            task.runtime_ms = round((time.perf_counter() - started) * 1000)
            task.llm_usage = list(usage)
            db.commit()
    finally:
        with _schedule_lock:
            _scheduled.discard(task_id)


def _schedule(task_id: str) -> None:
    with _schedule_lock:
        if task_id in _scheduled:
            return
        _scheduled.add(task_id)
    try:
        _executor.submit(_run_persisted, task_id)
    except Exception:
        with _schedule_lock:
            _scheduled.discard(task_id)
        raise


def enqueue_task(kind: str, payload: dict, *, user_id: str,
                 idempotency_key: str | None = None) -> str:
    """Save job inputs before execution; repeated submissions reuse the same task."""
    if kind not in {"generate", "post_generate", "submit", "post_submit", "retry_learning", "ticket_create", "ticket_finish"}:
        raise ValueError("未知的后台任务类型")
    if kind in {"generate", "post_generate"} and "generated_session_id" not in payload:
        payload = {**payload, "generated_session_id": uuid.uuid4().hex}
    task_id = (hashlib.sha256(f"{user_id}:{kind}:{idempotency_key}".encode()).hexdigest()[:32]
               if idempotency_key else uuid.uuid4().hex)
    with SessionLocal() as db:
        captured_profile = payload.get("profile_id") or current_profile_id(db, user_id)
        task = db.get(BackgroundTask, task_id)
        if task:
            if task.user_id != user_id or task.job_kind != kind or task.payload != payload:
                raise ValueError("重复提交的任务参数不一致")
            if task.status == "error":
                task.status, task.error = "pending", None
                db.commit()
        else:
            db.add(BackgroundTask(id=task_id, user_id=user_id, profile_id=captured_profile, status="pending",
                                  job_kind=kind, payload=payload))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.get(BackgroundTask, task_id)
                if not existing or existing.user_id != user_id or existing.job_kind != kind or existing.payload != payload:
                    raise ValueError("重复提交的任务参数不一致") from None
    if task is None or task.status == "pending":
        _schedule(task_id)
    return task_id


def mark_interrupted_tasks() -> None:
    """Replay saved jobs; legacy closure tasks remain non-replayable."""
    with SessionLocal() as db:
        pending = []
        for task in db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["pending", "running"])):
            if task.job_kind and task.payload is not None:
                task.status = "pending"
                pending.append(task.id)
            else:
                task.status = "error"
                task.error = "服务重启中断了任务，请重新提交"
        db.commit()
    for task_id in pending:
        _schedule(task_id)
