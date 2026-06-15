"""测评 API 路由（v3 - 三层 Track/Service/Capability）。"""
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


# ---------- 出题 / 提交 ----------

@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    """动态出题：基于 Service + Capability 生成。

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
    try:
        session_id, qs = generate_questions(
            service_id=req.service_id,
            capability_ids=req.capability_ids or None,
            num_choice=req.num_choice,
            num_open=req.num_open,
            difficulty=req.difficulty,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return GenerateResponse(session_id=session_id, questions=qs)


@router.post("/submit", response_model=AssessmentResult)
def submit(req: SubmitRequest):
    """提交答案（前测）。"""
    try:
        return run_assessment(
            user_id=req.user_id,
            answer_items=req.answers,
            session_id=req.session_id,
            kind="pre",
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/post-test/generate", response_model=GenerateResponse)
def post_test_generate(req: PostTestRequest):
    """后测出题：基于前测诊断出的知识盲区，针对性验证用户是否掌握了薄弱点。"""
    from app.db import SessionLocal
    from app.models import Assessment

    db = SessionLocal()
    try:
        prev = db.query(Assessment).filter_by(id=req.prev_assessment_id).first()
        if not prev or not prev.service_id:
            raise HTTPException(404, "前测记录不存在")
        service_id = prev.service_id

        # 从前测诊断盲区中提取薄弱 capability + 具体盲区描述
        diagnosis = prev.diagnosis or []
        weak_caps = list({g.get("capability_id") for g in diagnosis if g.get("capability_id")})

        # 如果诊断没有盲区（用户前测全对），fallback 到 radar 低分
        if not weak_caps:
            weak_caps = [r.get("capability_id") for r in (prev.radar or []) if r.get("score", 0) < 3.0 and r.get("capability_id")]

        # 构建盲区描述，注入给出题 prompt
        gap_hints = []
        for g in diagnosis:
            if g.get("severity") in ("critical", "major"):
                gap_hints.append(f"- [{g.get('capability_name','')}] {g.get('title','')}: {g.get('correct_understanding','')}")
    finally:
        db.close()

    # 把盲区信息作为额外上下文传给出题函数
    session_id, qs = generate_questions(
        service_id=service_id,
        capability_ids=weak_caps if weak_caps else None,
        post_test_gap_hints=gap_hints if gap_hints else None,
    )
    return GenerateResponse(session_id=session_id, questions=qs)


@router.post("/post-test/submit", response_model=AssessmentResult)
def post_test_submit(req: SubmitRequest):
    """提交后测答案，返回前后对比。"""
    parts = req.session_id.split(":", 1)
    session_id = parts[0]
    prev_id = parts[1] if len(parts) > 1 else ""

    return run_assessment(
        user_id=req.user_id,
        answer_items=req.answers,
        session_id=session_id,
        kind="post",
        prev_assessment_id=prev_id,
    )


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
