"""Traceable correction requests for assessment and simulated-ticket output."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.db import SessionLocal
from app.models import AdminAudit, Assessment, QualityFeedback, TicketSession
from app.services.profile_scope import current_profile_id, record_profile_id

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackInput(BaseModel):
    record_type: Literal["assessment", "ticket"]
    record_id: str = Field(min_length=1, max_length=32)
    question_id: str | None = Field(default=None, max_length=64)
    category: Literal["question", "answer", "score", "citation", "document", "ticket_case", "other"]
    description: str = Field(min_length=10, max_length=2000)


class ReviewInput(BaseModel):
    status: Literal["accepted", "rejected", "needs_info"]
    review_note: str = Field(min_length=10, max_length=2000)


def _serialize(row: QualityFeedback) -> dict:
    return {"id": row.id, "user_id": row.user_id, "profile_id": row.profile_id,
            "record_type": row.record_type, "record_id": row.record_id,
            "question_id": row.question_id, "category": row.category,
            "description": row.description, "original_snapshot": row.original_snapshot,
            "status": row.status, "review_note": row.review_note,
            "reviewed_by": row.reviewed_by,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


@router.post("")
def submit_feedback(req: FeedbackInput, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        profile = current_profile_id(db, current["uid"])
        record = db.get(Assessment if req.record_type == "assessment" else TicketSession, req.record_id)
        if not record or record.user_id != current["uid"] or record_profile_id(record) != profile:
            raise HTTPException(404, "记录不存在或不属于当前 Profile")
        snapshot: dict = {"service_id": record.service_id}
        if req.record_type == "assessment":
            if req.question_id:
                question = next((item for item in record.questions_snapshot or []
                                 if item.get("id") == req.question_id), None)
                if not question:
                    raise HTTPException(422, "题目不属于这次测评")
                snapshot["question"] = question
                snapshot["grade"] = next((item for item in record.question_results or []
                                          if item.get("question_id") == req.question_id), None)
            else:
                snapshot["overall_avg"] = record.overall_avg
        else:
            if req.question_id:
                raise HTTPException(422, "工单反馈不接受题目 ID")
            snapshot["report"] = record.report
            snapshot["case_id"] = record.case_id
        row = QualityFeedback(user_id=current["uid"], profile_id=profile,
                              record_type=req.record_type, record_id=req.record_id,
                              question_id=req.question_id, category=req.category,
                              description=req.description.strip(), original_snapshot=snapshot)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row)


@router.get("")
def list_feedback(profile_id: str | None = None, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        if current.get("r") == "manager":
            query = db.query(QualityFeedback)
            if profile_id:
                query = query.filter_by(profile_id=profile_id)
        else:
            query = db.query(QualityFeedback).filter_by(
                user_id=current["uid"], profile_id=current_profile_id(db, current["uid"]))
        return {"items": [_serialize(row) for row in query.order_by(QualityFeedback.created_at.desc()).limit(100).all()]}


@router.put("/{feedback_id}/review")
def review_feedback(feedback_id: str, req: ReviewInput,
                    current: dict = Depends(get_current_user)) -> dict:
    if current.get("r") != "manager":
        raise HTTPException(403, "仅管理员可复核")
    with SessionLocal() as db:
        row = db.get(QualityFeedback, feedback_id)
        if not row:
            raise HTTPException(404, "反馈不存在")
        row.status = req.status
        row.review_note = req.review_note.strip()
        row.reviewed_by = current["uid"]
        db.add(AdminAudit(actor_id=current["uid"], target_id=row.user_id,
                          action="review_quality_feedback",
                          detail=f"{row.id}:{req.status}"))
        db.commit()
        db.refresh(row)
        return _serialize(row)
