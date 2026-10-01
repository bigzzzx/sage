"""Fixed training assignments; completion is derived from subsequent evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.db import SessionLocal
from app.models import (AdminAudit, Assessment, QuestionSession, TicketSession,
                        TrainingAssignment, TrainingEnrollment, User)
from app.services.profile_scope import current_profile_id, service_in_profile
from app.services.taxonomy import get_service

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


class AssignmentInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=32)
    service_id: str = Field(min_length=1, max_length=32)
    kind: Literal["assessment", "ticket"]
    capability_id: str = Field(default="", max_length=64)
    question_count: Literal[6, 12, 18] = 12
    difficulty_profile: Literal["foundation", "balanced", "advanced"] = "balanced"
    focus: Literal["comprehensive", "configuration", "troubleshooting", "architecture"] = "comprehensive"
    note: str = Field(default="", max_length=500)
    due_at: datetime | None = None


def _completion(db, row: TrainingAssignment) -> tuple[str, str]:
    if row.kind == "ticket":
        ticket = db.query(TicketSession).filter_by(user_id=row.user_id, profile_id=row.profile_id,
                                                   service_id=row.service_id, status="closed").filter(
            TicketSession.created_at >= row.created_at).order_by(TicketSession.created_at.asc()).first()
        if ticket:
            return "completed", ticket.id
    else:
        assessments = db.query(Assessment).filter_by(user_id=row.user_id, profile_id=row.profile_id,
                                                      service_id=row.service_id, kind="pre",
                                                      record_origin="user").filter(
            Assessment.created_at >= row.created_at).order_by(Assessment.created_at.asc()).all()
        for assessment in assessments:
            session = db.get(QuestionSession, assessment.session_id) if assessment.session_id else None
            blueprint = session.blueprint if session else None
            if not blueprint or len(assessment.questions_snapshot or []) != row.question_count:
                continue
            if blueprint.get("difficulty_profile") != row.difficulty_profile:
                continue
            if blueprint.get("focus") != row.focus:
                continue
            if row.capability_id and row.capability_id not in blueprint.get("capability_ids", []):
                continue
            if bool(row.capability_id) != (blueprint.get("scope") == "focused"):
                continue
            from app.services.assessment import _assessment_scoring_version
            if _assessment_scoring_version(assessment.question_results or []) != row.scoring_version:
                continue
            return "completed", assessment.id
    now = datetime.now(timezone.utc)
    due = row.due_at.replace(tzinfo=timezone.utc) if row.due_at and row.due_at.tzinfo is None else row.due_at
    return ("overdue" if due and due < now else "pending"), ""


def _item(db, row: TrainingAssignment) -> dict:
    status, evidence_id = _completion(db, row)
    return {"id": row.id, "user_id": row.user_id, "profile_id": row.profile_id,
            "service_id": row.service_id, "kind": row.kind, "capability_id": row.capability_id,
            "question_count": row.question_count, "difficulty_profile": row.difficulty_profile,
            "focus": row.focus, "scoring_version": row.scoring_version,
            "note": row.note, "due_at": row.due_at.isoformat() if row.due_at else None,
            "created_by": row.created_by, "created_at": row.created_at.isoformat(),
            "status": status, "evidence_id": evidence_id}


@router.post("", status_code=201)
def create_assignment(req: AssignmentInput, current: dict = Depends(get_current_user)) -> dict:
    if current.get("r") != "manager":
        raise HTTPException(403, "仅管理员可布置培训")
    if not service_in_profile(req.service_id, req.profile_id):
        raise HTTPException(422, "服务不属于所选 Profile")
    service = get_service(req.service_id) or {}
    if req.capability_id and req.capability_id not in {cap["id"] for cap in service.get("capabilities", [])}:
        raise HTTPException(422, "能力点不属于所选服务")
    if req.kind == "ticket" and req.capability_id:
        raise HTTPException(422, "工单目前只按服务指定练习，不能承诺固定能力点")
    with SessionLocal() as db:
        user = db.get(User, req.user_id)
        if not user or user.role != "member" or not user.is_active:
            raise HTTPException(404, "有效成员不存在")
        if not db.query(TrainingEnrollment).filter_by(user_id=req.user_id,
                                                       profile_id=req.profile_id).first():
            raise HTTPException(409, "成员尚未加入此 Profile 的培训名单")
        existing = db.query(TrainingAssignment).filter_by(user_id=req.user_id,
            profile_id=req.profile_id, service_id=req.service_id, kind=req.kind).all()
        if any(_completion(db, assignment)[0] in {"pending", "overdue"} for assignment in existing):
            raise HTTPException(409, "该成员已有同服务、同类型的待完成任务")
        row = TrainingAssignment(user_id=req.user_id, profile_id=req.profile_id,
                                 service_id=req.service_id, kind=req.kind,
                                 capability_id=req.capability_id, question_count=req.question_count,
                                 difficulty_profile=req.difficulty_profile, focus=req.focus,
                                 scoring_version="assessment_v3", note=req.note.strip(),
                                 due_at=(req.due_at.astimezone(timezone.utc).replace(tzinfo=None)
                                         if req.due_at and req.due_at.tzinfo else req.due_at),
                                 created_by=current["uid"])
        db.add(row)
        db.flush()
        db.add(AdminAudit(actor_id=current["uid"], target_id=req.user_id,
                          action="assign_training", detail=row.id))
        db.commit()
        db.refresh(row)
        return _item(db, row)


@router.get("")
def list_assignments(profile_id: str | None = None,
                     current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        query = db.query(TrainingAssignment)
        if current.get("r") != "manager":
            query = query.filter_by(user_id=current["uid"],
                                    profile_id=current_profile_id(db, current["uid"]))
        elif profile_id:
            query = query.filter_by(profile_id=profile_id)
        rows = query.order_by(TrainingAssignment.created_at.desc()).limit(100).all()
        return {"items": [_item(db, row) for row in rows]}
