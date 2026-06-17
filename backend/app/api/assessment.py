"""测评 API 路由（v4 - 异步任务模式）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.assessment import (
    AssessmentResult,
    GenerateRequest,
    GenerateResponse,
    PostTestRequest,
    SubmitRequest,
)
from app.services.assessment import (
    get_pending_post_test,
    get_user_active_plans,
    get_user_history,
    get_user_track_radar,
    run_assessment,
)
from app.services.question_gen import generate_questions, get_session
from app.services.tasks import create_task, get_task, cleanup_task
from app.services.taxonomy import get_full_taxonomy, get_service, get_tracks

router = APIRouter(prefix="/api/assessment", tags=["assessment"])


# ---------- Taxonomy 查询 ----------

@router.get("/taxonomy")
def taxonomy():
    """获取完整 taxonomy（Track + Service + Capability）。"""
    return get_full_taxonomy()


@router.get("/tracks")
def list_tracks():
    """获取 Track + Service 简要信息。"""
    return get_tracks()


@router.get("/services/{service_id}")
def service_detail(service_id: str):
    svc = get_service(service_id)
    if not svc:
        raise HTTPException(404, detail=f"service {service_id} not found")
    return svc


# ---------- 异步任务轮询 ----------

@router.get("/task/{task_id}")
def task_status(task_id: str):
    """轮询异步任务状态。done 时返回 result，error 时返回 error。"""
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, detail="任务不存在或已过期")
    resp = {"status": t["status"]}
    if t["status"] == "done":
        resp["result"] = t["result"]
        cleanup_task(task_id)
    elif t["status"] == "error":
        resp["error"] = t["error"]
        cleanup_task(task_id)
    return resp


# ---------- 出题 / 提交（异步）----------

def _do_post_test_generate(prev_assessment_id: str) -> dict:
    """后测出题的实际逻辑（在后台线程执行）。"""
    from app.db import SessionLocal
    from app.models import Assessment

    db = SessionLocal()
    try:
        prev = db.query(Assessment).filter_by(id=prev_assessment_id).first()
        if not prev or not prev.service_id:
            raise ValueError("前测记录不存在")
        service_id = prev.service_id
        diagnosis = prev.diagnosis or []
        weak_caps = list({g.get("capability_id") for g in diagnosis if g.get("capability_id")})
        if not weak_caps:
            weak_caps = [r.get("capability_id") for r in (prev.radar or []) if r.get("score", 0) < 3.0 and r.get("capability_id")]
        gap_hints = []
        for g in diagnosis:
            if g.get("severity") in ("critical", "major"):
                gap_hints.append(f"- [{g.get('capability_name','')}] {g.get('title','')}: {g.get('correct_understanding','')}")
    finally:
        db.close()

    session_id, qs = generate_questions(
        service_id=service_id,
        capability_ids=weak_caps if weak_caps else None,
        post_test_gap_hints=gap_hints if gap_hints else None,
    )
    return {"session_id": session_id, "questions": qs}


@router.post("/generate")
def generate(req: GenerateRequest):
    """动态出题（异步）：立即返回 task_id，前端轮询 /task/{id} 拿结果。

    业务规则：同一服务下若有未完成的后测，禁止开新前测。
    """
    pending = get_pending_post_test(req.user_id, req.service_id)
    if pending:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PENDING_POST_TEST",
                "message": "请先完成上一轮的后测验证，再开始新一轮测评",
                "pending": pending,
            },
        )

    def _job():
        session_id, qs = generate_questions(
            service_id=req.service_id,
            capability_ids=req.capability_ids or None,
            num_choice=req.num_choice,
            num_open=req.num_open,
            difficulty=req.difficulty,
        )
        return {"session_id": session_id, "questions": qs}

    task_id = create_task(_job)
    return {"task_id": task_id}


@router.post("/submit")
def submit(req: SubmitRequest):
    """提交答案（前测，异步）：立即返回 task_id。"""
    def _job():
        result = run_assessment(
            user_id=req.user_id,
            answer_items=req.answers,
            session_id=req.session_id,
            kind="pre",
        )
        return result.model_dump()

    task_id = create_task(_job)
    return {"task_id": task_id}


@router.post("/post-test/generate")
def post_test_generate(req: PostTestRequest):
    """后测出题（异步）：立即返回 task_id。"""
    task_id = create_task(lambda: _do_post_test_generate(req.prev_assessment_id))
    return {"task_id": task_id}


@router.post("/post-test/submit")
def post_test_submit(req: SubmitRequest):
    """提交后测答案（异步）：立即返回 task_id。"""
    parts = req.session_id.split(":", 1)
    session_id = parts[0]
    prev_id = parts[1] if len(parts) > 1 else ""

    def _job():
        result = run_assessment(
            user_id=req.user_id,
            answer_items=req.answers,
            session_id=session_id,
            kind="post",
            prev_assessment_id=prev_id,
        )
        return result.model_dump()

    task_id = create_task(_job)
    return {"task_id": task_id}


# ---------- 用户历史与雷达图 ----------

@router.get("/history/{user_id}")
def history(user_id: str):
    return {"history": get_user_history(user_id)}


@router.get("/users/{user_id}/track-radar")
def user_track_radar(user_id: str, track_id: str = "big_data"):
    """获取用户在某 Track 下的全服务能力雷达图。"""
    return get_user_track_radar(user_id, track_id)


@router.get("/users/{user_id}/pending-post-test")
def user_pending_post_test(user_id: str, service_id: str = ""):
    """查询用户是否有未完成的后测。

    可选 service_id：传则只查该服务，不传只返回 None（跨服务允许并行）。
    """
    pending = get_pending_post_test(user_id, service_id or None)
    return {"pending": pending}


@router.get("/users/{user_id}/active-plans")
def user_active_plans(user_id: str, track_id: str = ""):
    """获取用户当前进行中的学习计划（每个 service 最多一条，后测完成后自动消失）。

    可选 track_id：传则只返回该 track 下的 service 的计划。
    """
    return {"plans": get_user_active_plans(user_id, track_id=track_id or None)}
