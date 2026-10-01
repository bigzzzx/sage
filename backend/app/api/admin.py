"""Administrator-only account management endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import _hash_password, get_current_user
from app.db import SessionLocal
from app.models import AdminAudit, Assessment, BackgroundTask, TicketSession, TrainingEnrollment, User
from app.services.assessment_summary import summarize_answers
from app.services.profile_scope import profile_filter
from app.services.taxonomy import get_profile_services
from sqlalchemy import func
from app.services.team_dashboard import build_team_dashboard

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/operations")
def operation_metrics(profile_id: str = "big_data", days: int = 30,
                      current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    if days not in {7, 30, 90} or not get_profile_services(profile_id):
        raise HTTPException(422, "时间范围或 Profile 无效")
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.query(BackgroundTask).filter(
            BackgroundTask.profile_id == profile_id,
            BackgroundTask.created_at >= since).order_by(BackgroundTask.created_at.desc()).limit(5000).all()
    try:
        prices = json.loads(os.environ.get("SAGE_LLM_PRICES_JSON", "{}"))
        if not isinstance(prices, dict):
            prices = {}
    except json.JSONDecodeError:
        prices = {}
    by_kind: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    unpriced_calls = 0
    usage_missing_calls = 0
    unobserved_tasks = 0
    estimated_usd = 0.0
    for row in rows:
        if row.llm_usage is None and row.job_kind in {"generate", "post_generate", "submit", "post_submit",
                                                        "retry_learning", "ticket_create", "ticket_finish"}:
            unobserved_tasks += 1
        kind = row.job_kind or "legacy"
        bucket = by_kind.setdefault(kind, {"total": 0, "done": 0, "error": 0,
                                           "pending": 0, "latencies_ms": []})
        bucket["total"] += 1
        bucket[row.status if row.status in {"done", "error"} else "pending"] += 1
        if row.runtime_ms is not None and row.status in {"done", "error"}:
            bucket["latencies_ms"].append(row.runtime_ms)
        for call in row.llm_usage or []:
            model = str(call.get("model") or "unknown")
            entry = by_model.setdefault(model, {"calls": 0, "failed": 0,
                                                "prompt_tokens": 0, "completion_tokens": 0,
                                                "token_usage_missing": 0})
            entry["calls"] += 1
            entry["failed"] += call.get("status") == "failed"
            prompt, completion = call.get("prompt_tokens"), call.get("completion_tokens")
            if prompt is None or completion is None:
                entry["token_usage_missing"] += 1
                usage_missing_calls += 1
            else:
                entry["prompt_tokens"] += prompt
                entry["completion_tokens"] += completion
                rate = prices.get(model) if isinstance(prices.get(model), dict) else None
                try:
                    input_rate = float(rate["input_per_million"]) if rate else -1
                    output_rate = float(rate["output_per_million"]) if rate else -1
                except (KeyError, TypeError, ValueError):
                    input_rate = output_rate = -1
                if math.isfinite(input_rate) and math.isfinite(output_rate) and input_rate >= 0 and output_rate >= 0:
                    estimated_usd += (prompt * input_rate + completion * output_rate) / 1_000_000
                else:
                    unpriced_calls += 1
    def percentile(values: list[int], quantile: float) -> int | None:
        if not values:
            return None
        sorted_values = sorted(values)
        return sorted_values[min(len(sorted_values) - 1, int((len(sorted_values) - 1) * quantile))]
    summary = [{"kind": kind, "total": data["total"], "done": data["done"],
                "error": data["error"], "pending": data["pending"],
                "p50_ms": percentile(data["latencies_ms"], .5),
                "p95_ms": percentile(data["latencies_ms"], .95)}
               for kind, data in sorted(by_kind.items())]
    return {"profile_id": profile_id, "days": days, "sample_count": len(rows),
            "truncated": len(rows) == 5000, "by_kind": summary, "by_model": by_model,
            "estimated_usd": round(estimated_usd, 6) if prices and not unpriced_calls and not usage_missing_calls and not unobserved_tasks else None,
            "unpriced_calls": unpriced_calls, "unobserved_tasks": unobserved_tasks,
            "note": "仅统计后台任务；模型调用明细从本次更新后开始采集，历史任务和同步客户对话不含 token 用量。费用仅在所有调用均有 token 用量和有效单价时展示。"}


@router.get("/dashboard")
def team_dashboard(profile_id: str = "big_data", days: int = 0,
                   include_demo: bool = False, enrolled_only: bool = False,
                   current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    if days not in {0, 30, 90}:
        raise HTTPException(422, "时间范围仅支持全部、近 30 天或近 90 天")
    try:
        return build_team_dashboard(profile_id, days, include_demo, enrolled_only)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _require_manager(current: dict) -> None:
    if current.get("r") != "manager":
        raise HTTPException(403, "仅管理员可管理账号")


class CreateAccountRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    display_name: str = Field(default="", max_length=64)
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["member", "manager"] = "member"


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class AccountStatusRequest(BaseModel):
    is_active: bool | None = None
    is_demo: bool | None = None


class EnrollmentRequest(BaseModel):
    profile_id: str
    enrolled: bool


@router.get("/enrollments")
def list_enrollments(profile_id: str, current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    if not get_profile_services(profile_id):
        raise HTTPException(422, "未知的 Profile")
    with SessionLocal() as db:
        return {"user_ids": [row.user_id for row in db.query(TrainingEnrollment).filter_by(profile_id=profile_id).all()]}


@router.put("/enrollments/{user_id}")
def set_enrollment(user_id: str, req: EnrollmentRequest,
                   current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    if not get_profile_services(req.profile_id):
        raise HTTPException(422, "未知的 Profile")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or user.role != "member":
            raise HTTPException(404, "成员不存在")
        existing = db.query(TrainingEnrollment).filter_by(user_id=user_id, profile_id=req.profile_id).first()
        if req.enrolled and not existing:
            db.add(TrainingEnrollment(user_id=user_id, profile_id=req.profile_id))
        elif not req.enrolled and existing:
            db.delete(existing)
        db.add(AdminAudit(actor_id=current["uid"], target_id=user_id, action="set_enrollment",
                          detail=f"profile={req.profile_id},enrolled={req.enrolled}"))
        db.commit()
        return {"user_id": user_id, "profile_id": req.profile_id, "enrolled": req.enrolled}


def _serialize_user(user: User) -> dict:
    created = user.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {"user_id": user.id, "username": user.username,
            "display_name": user.display_name, "role": user.role,
            "current_profile": user.current_profile,
            "is_active": user.is_active, "is_demo": user.is_demo,
            "must_change_password": user.must_change_password,
            "created_at": created.isoformat() if created else ""}


@router.get("/users")
def list_accounts(current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    with SessionLocal() as db:
        rows = db.query(User).order_by(User.created_at.asc(), User.username.asc()).all()
        return {"users": [_serialize_user(row) for row in rows]}


@router.post("/users", status_code=201)
def create_account(req: CreateAccountRequest,
                   current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    username = req.username.strip()
    if not username.isascii() or not username.replace("_", "").isalnum():
        raise HTTPException(422, "用户名须为 2-32 位 ASCII 字母、数字或下划线")
    with SessionLocal() as db:
        if db.query(User.id).filter(User.username == username).first():
            raise HTTPException(409, "用户名已存在")
        user = User(username=username,
                    display_name=req.display_name.strip() or username,
                    password_hash=_hash_password(req.password),
                    role=req.role, current_profile="big_data", must_change_password=True)
        db.add(user)
        db.flush()
        db.add(AdminAudit(actor_id=current["uid"], target_id=user.id, action="create_account", detail=req.role))
        db.commit()
        db.refresh(user)
        return _serialize_user(user)


@router.put("/users/{user_id}/password")
def reset_account_password(user_id: str, req: ResetPasswordRequest,
                           current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "账号不存在")
        user.password_hash = _hash_password(req.password)
        user.token_version += 1
        user.must_change_password = True
        db.add(AdminAudit(actor_id=current["uid"], target_id=user.id, action="reset_password"))
        db.commit()
        return {"ok": True, "sessions_revoked": True}


@router.patch("/users/{user_id}/status")
def update_account_status(user_id: str, req: AccountStatusRequest,
                          current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    if req.is_active is None and req.is_demo is None:
        raise HTTPException(422, "没有需要修改的字段")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "账号不存在")
        if req.is_active is False and user.id == current["uid"]:
            raise HTTPException(400, "不能停用当前管理员账号")
        if req.is_active is False and user.role == "manager":
            other = db.query(User.id).filter(User.role == "manager", User.is_active.is_(True), User.id != user.id).first()
            if not other:
                raise HTTPException(400, "不能停用最后一位管理员")
        if req.is_active is not None and req.is_active != user.is_active:
            user.is_active = req.is_active
            user.token_version += 1
        if req.is_demo is not None:
            user.is_demo = req.is_demo
        db.add(AdminAudit(actor_id=current["uid"], target_id=user.id, action="update_status",
                          detail=f"active={user.is_active},demo={user.is_demo}"))
        db.commit()
        return _serialize_user(user)


@router.get("/audit")
def list_audit(limit: int = 50, current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    limit = max(1, min(limit, 100))
    with SessionLocal() as db:
        rows = db.query(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit).all()
        return {"items": [{"actor_id": row.actor_id, "target_id": row.target_id,
                           "action": row.action, "detail": row.detail,
                           "created_at": row.created_at.isoformat()} for row in rows]}


@router.get("/members/{user_id}")
def member_detail(user_id: str, profile_id: str = "big_data",
                  current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    if not get_profile_services(profile_id):
        raise HTTPException(422, "未知的 Profile")
    with SessionLocal() as db:
        member = db.get(User, user_id)
        if not member or member.role != "member":
            raise HTTPException(404, "成员不存在")
        assessments = (db.query(Assessment).filter(
            Assessment.user_id == user_id, profile_filter(Assessment, profile_id),
            func.coalesce(Assessment.record_origin, "user") != "agent_test")
            .order_by(Assessment.created_at.desc()).limit(30).all())
        tickets = (db.query(TicketSession).filter(
            TicketSession.user_id == user_id, profile_filter(TicketSession, profile_id))
            .order_by(TicketSession.created_at.desc()).limit(30).all())
        return {"member": _serialize_user(member), "profile_id": profile_id,
                "assessments": [{"id": row.id, "service_id": row.service_id,
                                 "kind": row.kind, "created_at": row.created_at.isoformat(),
                                 "score": (summary := summarize_answers(row.questions_snapshot or [], row.question_results or []))["overall_avg"],
                                 "rating_reliable": summary["rating_reliable"],
                                 "question_count": summary["question_count"],
                                 "has_plan": bool(row.learning_plan)} for row in assessments],
                "tickets": [{"id": row.id, "service_id": row.service_id,
                             "status": row.status, "created_at": row.created_at.isoformat(),
                             "category": row.category} for row in tickets]}


@router.get("/members/{user_id}/assessments/{assessment_id}")
def manager_assessment_detail(user_id: str, assessment_id: str, profile_id: str = "big_data",
                              current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    with SessionLocal() as db:
        row = db.get(Assessment, assessment_id)
        if not row or row.user_id != user_id or not db.query(Assessment.id).filter(
                Assessment.id == assessment_id, profile_filter(Assessment, profile_id),
                func.coalesce(Assessment.record_origin, "user") != "agent_test").first():
            raise HTTPException(404, "测评记录不存在")
        return {"record_type": "assessment", "id": row.id, "service_id": row.service_id, "kind": row.kind,
                "summary": summarize_answers(row.questions_snapshot or [], row.question_results or []),
                "diagnosis": row.diagnosis or [], "plan_review": row.plan_review or {},
                "learning_plan": row.learning_plan, "question_results": row.question_results or []}


@router.get("/members/{user_id}/tickets/{ticket_id}")
def manager_ticket_detail(user_id: str, ticket_id: str, profile_id: str = "big_data",
                          current: dict = Depends(get_current_user)) -> dict:
    _require_manager(current)
    with SessionLocal() as db:
        row = db.get(TicketSession, ticket_id)
        if not row or row.user_id != user_id or not db.query(TicketSession.id).filter(
                TicketSession.id == ticket_id, profile_filter(TicketSession, profile_id)).first():
            raise HTTPException(404, "工单不存在")
        return {"record_type": "ticket", "id": row.id, "service_id": row.service_id, "status": row.status,
                "messages": row.messages or [], "final_answer": row.final_answer,
                "report": row.report or {}}
