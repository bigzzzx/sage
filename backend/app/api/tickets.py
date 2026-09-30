"""Persistent, owner-scoped chat ticket training API."""
from __future__ import annotations

import secrets
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.api.auth import get_current_user
from app.config import get_settings
from app.db import SessionLocal
from app.models import TicketSession, User
from app.services.llm import resolve_generation_model
from app.services.taxonomy import get_profile_services
from app.services.profile_scope import current_profile_id, profile_filter, record_profile_id, service_in_profile
from app.services.ticket_dialogue import initial_state, public_state
from app.services.tasks import enqueue_task, get_task
from app.services.ticket_simulation import (
    CATEGORIES, DIFFICULTIES, IMPACTS, MAX_USER_TURNS, PERSONAS, choose_case,
    customer_opening, customer_turn, generate_case, get_case, grade_ticket, load_cases,
)

router = APIRouter(prefix="/api/practice/tickets", tags=["ticket-practice"])


class StartTicketRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    service_id: str = "glue"
    category: str
    persona_id: str
    model_id: str | None = None
    impact: str = "production_degraded"
    difficulty: str = "intermediate"
    cross_service: bool = False


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=2, max_length=1200)


class FinishTicketRequest(BaseModel):
    final_answer: str = Field(min_length=30, max_length=4000)


class CreateTaskRequest(StartTicketRequest):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class FinishTaskRequest(FinishTicketRequest):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


def _owned_ticket(db, ticket_id: str, user_id: str, profile_id: str | None = None) -> TicketSession:
    ticket = db.get(TicketSession, ticket_id)
    expected = profile_id or current_profile_id(db, user_id)
    if not ticket or ticket.user_id != user_id or record_profile_id(ticket) != expected:
        raise HTTPException(404, "工单不存在")
    return ticket


def _ticket_case(ticket: TicketSession) -> dict:
    return ticket.case_data or get_case(ticket.case_id)


def _public_ticket(ticket: TicketSession) -> dict:
    case = _ticket_case(ticket)
    persona = PERSONAS[ticket.persona_id]
    category = CATEGORIES[ticket.category]
    return {
        "ticket_id": ticket.id,
        "service_id": ticket.service_id,
        "category": ticket.category,
        "category_label": category["label"],
        "persona_id": ticket.persona_id,
        "persona_label": persona["label"],
        "persona_traits": {"expertise": persona["expertise"], "patience": persona["patience"],
                           "cooperation": persona["cooperation"]},
        "customer_name": ticket.customer_name,
        "title": case["title"],
        "model_id": ticket.model_id,
        "impact": ticket.impact or "production_degraded",
        "impact_label": IMPACTS.get(ticket.impact or "", IMPACTS["production_degraded"]),
        "difficulty": ticket.difficulty or "intermediate",
        "difficulty_label": DIFFICULTIES.get(ticket.difficulty or "", DIFFICULTIES["intermediate"]),
        "cross_service": bool(ticket.cross_service),
        "case_origin": "generated" if case.get("generated") else "curated",
        "case_quality": {"status": case.get("quality", {}).get("status", "legacy_unreviewed"),
                         "source_status": case.get("quality", {}).get("source_status", "unverified"),
                         "snapshot_sha256": case.get("quality", {}).get("snapshot_sha256", "")},
        "customer_state": public_state(
            ticket.conversation_state or initial_state(persona, ticket.messages), case),
        "status": ticket.status,
        "messages": ticket.messages or [],
        "turn_count": sum(item.get("role") == "user" for item in ticket.messages or []),
        "max_turns": MAX_USER_TURNS,
        "report": ticket.report if ticket.status == "closed" else None,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else "",
    }


@router.get("/options")
def ticket_options(current: dict = Depends(get_current_user)) -> dict:
    counts = {key: sum(case["category"] == key for case in load_cases()) for key in CATEGORIES}
    with SessionLocal() as db:
        user = db.get(User, current["uid"])
        if not user:
            raise HTTPException(404, "用户不存在")
        profile_id = user.current_profile
    services = get_profile_services(profile_id)
    return {
        "profile_id": profile_id,
        "services": [{"id": item["id"], "label": item["name"], "summary": item.get("summary", "")}
                     for item in services],
        "categories": [{"id": key, "label": value["label"], "description": value["description"],
                        "curated_case_count": counts[key]} for key, value in CATEGORIES.items()],
        "personas": [{"id": key, "label": value["label"], "description": value["style"],
                      "expertise": value["expertise"], "patience": value["patience"],
                      "cooperation": value["cooperation"]}
                     for key, value in PERSONAS.items() if not value.get("legacy")],
        "impacts": [{"id": key, "label": value} for key, value in IMPACTS.items()],
        "difficulties": [{"id": key, "label": value} for key, value in DIFFICULTIES.items()],
        "requires_model": True,
    }


@router.get("")
def list_tickets(limit: int = Query(30, ge=1, le=50), offset: int = Query(0, ge=0),
                 service_id: str = Query("", max_length=32), status: str = Query("", max_length=16),
                 q: str = Query("", max_length=80),
                 current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        profile_id = current_profile_id(db, current["uid"])
        if not profile_id:
            return {"tickets": [], "total": 0, "limit": limit, "offset": offset}
        query = db.query(TicketSession).filter_by(user_id=current["uid"]).filter(
            profile_filter(TicketSession, profile_id))
        if service_id:
            query = query.filter(TicketSession.service_id == service_id)
        if status in {"open", "closed"}:
            query = query.filter(TicketSession.status == status)
        if q.strip():
            from sqlalchemy import func
            term = f"%{q.strip().lower()}%"
            query = query.filter(TicketSession.service_id.ilike(term) |
                                 TicketSession.case_id.ilike(term) |
                                 func.json_extract(TicketSession.case_data, "$.title").ilike(term))
        total = query.count()
        rows = (query.order_by(TicketSession.created_at.desc(), TicketSession.id.desc())
                .offset(offset).limit(limit).all())
        return {"tickets": [{"ticket_id": row.id, "title": _ticket_case(row)["title"],
                             "category_label": CATEGORIES[row.category]["label"], "status": row.status,
                             "overall_score": (row.report or {}).get("overall_score"),
                             "created_at": row.created_at.isoformat() if row.created_at else ""}
                            for row in rows], "total": total, "limit": limit, "offset": offset}


def create_ticket(req: StartTicketRequest, current: dict, ticket_id: str | None = None,
                  profile_id: str | None = None) -> dict:
    if ticket_id:
        with SessionLocal() as db:
            existing = db.get(TicketSession, ticket_id)
            if existing:
                return _public_ticket(_owned_ticket(db, ticket_id, current["uid"], profile_id))
    if (req.category not in CATEGORIES or req.persona_id not in PERSONAS
            or req.impact not in IMPACTS or req.difficulty not in DIFFICULTIES):
        raise HTTPException(400, "暂不支持该服务、类别或客户画像")
    if not get_settings().llm_api_key:
        raise HTTPException(503, "工单对话需要先配置模型服务")
    try:
        model_id = resolve_generation_model(req.model_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with SessionLocal() as db:
        user = db.get(User, current["uid"])
        if not user:
            raise HTTPException(404, "用户不存在")
        selected_profile = profile_id or user.current_profile
        if not service_in_profile(req.service_id, selected_profile):
            raise HTTPException(400, "该服务不属于当前 Profile")
        used = {((row.case_data or {}).get("seed_id") or row.case_id) for row in db.query(TicketSession)
                .filter_by(user_id=current["uid"], service_id=req.service_id,
                           category=req.category).all()}
    seed = choose_case(req.category, used, service_id=req.service_id, difficulty=req.difficulty,
                       impact=req.impact, cross_service=req.cross_service)
    try:
        case = generate_case(req.service_id, req.category, req.difficulty,
                             req.cross_service, model_id, req.impact, seed)
    except ValueError as exc:
        raise HTTPException(503, "工单未通过案例质量检查，请重新生成") from exc
    except Exception as exc:
        raise HTTPException(503, "模拟工单生成失败，请重试") from exc
    with SessionLocal() as db:
        customer_name = secrets.choice(PERSONAS[req.persona_id]["names"])
        ticket = TicketSession(
            user_id=current["uid"], profile_id=selected_profile, service_id=req.service_id, category=req.category,
            persona_id=req.persona_id, customer_name=customer_name,
            case_id=case["id"], case_data=case, model_id=model_id, impact=req.impact,
            difficulty=req.difficulty, cross_service=req.cross_service,
            messages=[{"role": "customer", "content": customer_opening(
                case, req.persona_id, customer_name, req.impact)}],
            revealed_evidence_ids=[], conversation_state=initial_state(PERSONAS[req.persona_id]),
        )
        if ticket_id:
            ticket.id = ticket_id
        db.add(ticket)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if ticket_id:
                return _public_ticket(_owned_ticket(db, ticket_id, current["uid"], selected_profile))
            raise
        db.refresh(ticket)
        return _public_ticket(ticket)


@router.post("", status_code=201)
def start_ticket(req: StartTicketRequest, current: dict = Depends(get_current_user)) -> dict:
    return create_ticket(req, current)


@router.post("/create-task", status_code=202)
def create_ticket_task(req: CreateTaskRequest, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        user = db.get(User, current["uid"])
        if not user or req.service_id not in {s["id"] for s in get_profile_services(user.current_profile)}:
            raise HTTPException(400, "该服务不属于当前 Profile")
        profile_id = user.current_profile
    if (req.category not in CATEGORIES or req.persona_id not in PERSONAS
            or req.impact not in IMPACTS or req.difficulty not in DIFFICULTIES):
        raise HTTPException(400, "工单配置无效")
    payload = req.model_dump(exclude={"request_id"})
    payload["profile_id"] = profile_id
    payload["ticket_id"] = hashlib.sha256(f"{current['uid']}:{req.request_id}".encode()).hexdigest()[:32]
    try:
        task_id = enqueue_task("ticket_create", payload, user_id=current["uid"], idempotency_key=req.request_id)
    except ValueError as exc:
        raise HTTPException(409, "工单请求参数与之前的提交不一致") from exc
    return {"task_id": task_id}


@router.get("/tasks/{task_id}")
def ticket_task_status(task_id: str, current: dict = Depends(get_current_user)) -> dict:
    task = get_task(task_id, user_id=current["uid"])
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        return _public_ticket(_owned_ticket(db, ticket_id, current["uid"]))


@router.post("/{ticket_id}/messages")
def send_message(ticket_id: str, req: SendMessageRequest,
                 current: dict = Depends(get_current_user)) -> dict:
    question = req.message.strip()
    if len(question) < 2:
        raise HTTPException(400, "请输入要向客户询问的内容")
    with SessionLocal() as db:
        ticket = _owned_ticket(db, ticket_id, current["uid"])
        if ticket.status != "open":
            raise HTTPException(409, "工单已结案")
        messages = list(ticket.messages or [])
        if sum(item.get("role") == "user" for item in messages) >= MAX_USER_TURNS:
            raise HTTPException(409, "对话轮次已用完，请提交最终处理方案")
        case, persona_id = _ticket_case(ticket), ticket.persona_id
        customer_name, model_id = ticket.customer_name, ticket.model_id
        state = ticket.conversation_state or initial_state(PERSONAS[persona_id], messages)
    try:
        turn = customer_turn(case, persona_id, customer_name, messages, question, model_id, state)
    except Exception as exc:
        raise HTTPException(503, "模拟客户暂时无法回复，请重试") from exc
    with SessionLocal() as db:
        ticket = _owned_ticket(db, ticket_id, current["uid"])
        changed = db.execute(update(TicketSession).where(
            TicketSession.id == ticket_id, TicketSession.user_id == current["uid"],
            TicketSession.status == "open", TicketSession.messages == messages).values(
                messages=[*messages, {"role": "user", "content": question},
                          {"role": "customer", "content": turn["reply"], "evidence_ids": turn["evidence_ids"]}],
                conversation_state=turn["state"],
                revealed_evidence_ids=turn["state"]["known_evidence_ids"]))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "工单状态已变化，请刷新后重试")
        db.commit()
        db.refresh(ticket)
        return _public_ticket(ticket)


@router.post("/{ticket_id}/finish")
def finish_ticket(ticket_id: str, req: FinishTicketRequest,
                  current: dict = Depends(get_current_user)) -> dict:
    return _finish_ticket(ticket_id, req, current)


def _finish_ticket(ticket_id: str, req: FinishTicketRequest, current: dict,
                   profile_id: str | None = None) -> dict:
    answer = req.final_answer.strip()
    if len(answer) < 30:
        raise HTTPException(400, "处理方案至少需要 30 个有效字符")
    with SessionLocal() as db:
        ticket = _owned_ticket(db, ticket_id, current["uid"], profile_id)
        if ticket.status == "closed":
            return _public_ticket(ticket)
        messages = list(ticket.messages or [])
        if sum(item.get("role") == "user" for item in messages) < 2:
            raise HTTPException(400, "请先与客户进行至少两轮排查交流")
        case, model_id, persona_id = _ticket_case(ticket), ticket.model_id, ticket.persona_id
        revealed = list(ticket.revealed_evidence_ids or [])
        state = ticket.conversation_state or initial_state(PERSONAS[persona_id], messages)
    try:
        report = grade_ticket(case, messages, answer, revealed, model_id, persona_id, state)
    except Exception as exc:
        raise HTTPException(503, "工单报告生成失败，答案未提交，请重试") from exc
    with SessionLocal() as db:
        ticket = _owned_ticket(db, ticket_id, current["uid"], profile_id)
        changed = db.execute(update(TicketSession).where(
            TicketSession.id == ticket_id, TicketSession.user_id == current["uid"],
            TicketSession.status == "open", TicketSession.messages == messages).values(
                final_answer=answer, report=report, status="closed",
                messages=[*messages, {"role": "user", "content": answer,
                                      "kind": "final_summary"}]))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "工单状态已变化，请刷新后重试")
        db.commit()
        db.refresh(ticket)
        return _public_ticket(ticket)


@router.post("/{ticket_id}/finish-task", status_code=202)
def finish_ticket_task(ticket_id: str, req: FinishTaskRequest,
                       current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        ticket = _owned_ticket(db, ticket_id, current["uid"])
        profile_id = record_profile_id(ticket)
    try:
        task_id = enqueue_task("ticket_finish", {"ticket_id": ticket_id, "profile_id": profile_id,
            "final_answer": req.final_answer}, user_id=current["uid"], idempotency_key=req.request_id)
    except ValueError as exc:
        raise HTTPException(409, "工单请求参数与之前的提交不一致") from exc
    return {"task_id": task_id}
