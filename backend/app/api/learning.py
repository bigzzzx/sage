"""Task evidence in a generated learning plan, scoped to its assessment owner."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.api.auth import get_current_user
from app.db import SessionLocal
from app.models import AdminAudit, Assessment, LearningTaskProgress
from app.services.profile_scope import current_profile_id, record_profile_id

router = APIRouter(prefix="/api/learning", tags=["learning"])


class TaskEvidence(BaseModel):
    week_index: int = Field(ge=0)
    task_index: int = Field(ge=0)
    evidence: str = Field(default="", max_length=4000)
    status: Literal["in_progress", "blocked", "submitted"] = "submitted"


class TaskReview(BaseModel):
    accepted: bool
    review_note: str = Field(min_length=10, max_length=2000)


def _owned_plan(db, assessment_id: str, user_id: str) -> list:
    assessment = db.get(Assessment, assessment_id)
    if (not assessment or assessment.user_id != user_id or not assessment.learning_plan
            or record_profile_id(assessment) != current_profile_id(db, user_id)):
        raise HTTPException(404, "学习计划不存在")
    return assessment.learning_plan.get("weekly_plan") or []


def _item(row: LearningTaskProgress) -> dict:
    return {"week_index": row.week_index, "task_index": row.task_index,
            "evidence": row.evidence, "status": "submitted" if row.status == "completed" else row.status,
            "review_note": row.review_note or "", "reviewed_by": row.reviewed_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else ""}


@router.get("/plans/{assessment_id}/progress")
def get_progress(assessment_id: str, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        _owned_plan(db, assessment_id, current["uid"])
        rows = db.query(LearningTaskProgress).filter_by(assessment_id=assessment_id, user_id=current["uid"]).all()
        return {"progress": [_item(row) for row in rows]}


@router.put("/plans/{assessment_id}/progress")
def save_progress(assessment_id: str, req: TaskEvidence, current: dict = Depends(get_current_user)) -> dict:
    if req.status in {"blocked", "submitted"} and len(req.evidence.strip()) < 10:
        raise HTTPException(422, "受阻原因或完成证据至少需要 10 字")
    with SessionLocal() as db:
        weeks = _owned_plan(db, assessment_id, current["uid"])
        if req.week_index >= len(weeks) or req.task_index >= len(weeks[req.week_index].get("tasks", [])):
            raise HTTPException(400, "学习任务索引无效")
        row = db.query(LearningTaskProgress).filter_by(assessment_id=assessment_id,
            week_index=req.week_index, task_index=req.task_index).first()
        if row and row.user_id != current["uid"]:
            raise HTTPException(404, "学习任务不存在")
        if row and row.status == "verified":
            raise HTTPException(409, "该任务已通过管理员验收，不能再改写证据")
        if not row:
            row = LearningTaskProgress(user_id=current["uid"], assessment_id=assessment_id,
                week_index=req.week_index, task_index=req.task_index, evidence=req.evidence.strip(), status=req.status)
            db.add(row)
        else:
            row.evidence = req.evidence.strip()
            row.status = req.status
            row.review_note = None
            row.reviewed_by = None
        db.commit()
        db.refresh(row)
        return _item(row)


@router.get("/review-queue")
def review_queue(profile_id: str = "big_data", current: dict = Depends(get_current_user)) -> dict:
    if current.get("r") != "manager":
        raise HTTPException(403, "仅管理员可查看学习证据")
    with SessionLocal() as db:
        rows = db.query(LearningTaskProgress, Assessment).join(
            Assessment, LearningTaskProgress.assessment_id == Assessment.id).filter(
            Assessment.profile_id == profile_id,
            LearningTaskProgress.status.in_(["submitted", "completed"])).all()
        return {"items": [{"id": row.id, "user_id": row.user_id, "assessment_id": row.assessment_id,
                           "service_id": assessment.service_id, **_item(row)} for row, assessment in rows]}


@router.put("/progress/{progress_id}/review")
def review_progress(progress_id: str, req: TaskReview,
                    current: dict = Depends(get_current_user)) -> dict:
    if current.get("r") != "manager":
        raise HTTPException(403, "仅管理员可验收学习证据")
    with SessionLocal() as db:
        row = db.get(LearningTaskProgress, progress_id)
        if not row or row.status not in {"submitted", "completed"}:
            raise HTTPException(404, "待验收任务不存在")
        row.status = "verified" if req.accepted else "blocked"
        row.review_note = req.review_note.strip()
        row.reviewed_by = current["uid"]
        db.add(AdminAudit(actor_id=current["uid"], target_id=row.user_id,
                          action="review_learning_task", detail=f"{row.id}:{row.status}"))
        db.commit()
        db.refresh(row)
        return _item(row)
