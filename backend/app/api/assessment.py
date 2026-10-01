"""测评 API 路由（v4 - 异步任务模式）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.auth import get_current_user
from app.db import SessionLocal
from app.config import get_settings

from app.schemas.assessment import (
    AssessmentResult,
    GenerateRequest,
    GenerateResponse,
    PostTestRequest,
    SubmitRequest,
)
from app.services.assessment import (
    get_pending_post_test,
    get_team_track_radar,
    get_user_active_plans,
    get_user_archive,
    get_user_history,
    get_user_track_radar,
    load_assessment_result,
    run_assessment,
)
from app.services.question_gen import generate_questions, get_session, public_questions
from app.services.llm import resolve_generation_model
from app.services.tasks import enqueue_task, get_task
from app.services.taxonomy import get_full_taxonomy, get_service, get_tracks
from app.services.profile_scope import current_profile_id, record_profile_id, service_in_profile
from app.services.profile_insights import get_user_profile_insights

router = APIRouter(prefix="/api/assessment", tags=["assessment"])


def _require_llm_ready() -> None:
    if not get_settings().llm_api_key:
        raise HTTPException(503, "AI 测评暂不可用：服务端未配置 LLM_API_KEY")


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
def task_status(task_id: str, current: dict = Depends(get_current_user)):
    """轮询异步任务状态。done 时返回 result，error 时返回 error。"""
    t = get_task(task_id, user_id=current["uid"])
    if not t:
        raise HTTPException(404, detail="任务不存在或已过期")
    resp = {"status": t["status"]}
    if t["status"] == "done":
        resp["result"] = t["result"]
    elif t["status"] == "error":
        resp["error"] = t["error"]
    return resp


# ---------- 出题 / 提交（异步）----------

def _do_post_test_generate(prev_assessment_id: str, user_id: str,
                           model_id: str | None = None,
                           generated_session_id: str | None = None) -> dict:
    """后测出题的实际逻辑（在后台线程执行）。"""
    from app.db import SessionLocal
    from app.models import Assessment

    db = SessionLocal()
    try:
        prev = db.query(Assessment).filter_by(id=prev_assessment_id).first()
        if not prev or prev.user_id != user_id or not prev.service_id or prev.kind != "pre":
            raise ValueError("前测记录不存在")
        service_id = prev.service_id
        profile_id = record_profile_id(prev)
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
        user_id=user_id,
        kind="post",
        prev_assessment_id=prev_assessment_id,
        model_id=model_id,
        profile_id=profile_id,
        session_id=generated_session_id,
    )
    return {"session_id": session_id, "questions": public_questions(qs)}


@router.post("/generate")
def generate(req: GenerateRequest, current: dict = Depends(get_current_user)):
    """动态出题（异步）：立即返回 task_id，前端轮询 /task/{id} 拿结果。

    业务规则：同一服务下若有未完成的后测，禁止开新前测。
    """
    _require_llm_ready()
    with SessionLocal() as db:
        profile_id = current_profile_id(db, current["uid"])
    if not service_in_profile(req.service_id, profile_id):
        raise HTTPException(400, "该服务不属于当前 Profile")
    try:
        model_id = resolve_generation_model(req.generation_model)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    pending = get_pending_post_test(current["uid"], req.service_id)
    if pending:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PENDING_POST_TEST",
                "message": "请先完成上一轮的后测验证，再开始新一轮测评",
                "pending": pending,
            },
        )

    task_id = enqueue_task("generate", {
        "service_id": req.service_id, "profile_id": profile_id, "capability_ids": req.capability_ids,
        "question_count": req.question_count, "difficulty_profile": req.difficulty_profile,
        "focus": req.focus, "model_id": model_id,
        "study_days": req.study_days, "minutes_per_day": req.minutes_per_day,
    }, user_id=current["uid"])
    return {"task_id": task_id}


@router.post("/submit")
def submit(req: SubmitRequest, current: dict = Depends(get_current_user)):
    """提交答案（前测，异步）：立即返回 task_id。"""
    _require_llm_ready()
    session = get_session(req.session_id, current["uid"])
    if not session or session["kind"] != "pre" or not _is_current_profile(current["uid"], session["profile_id"]):
        raise HTTPException(404, "测评会话不存在")

    try:
        task_id = enqueue_task("submit", {
            "session_id": req.session_id,
            "profile_id": session["profile_id"],
            "answers": [item.model_dump() for item in req.answers],
        }, user_id=current["uid"], idempotency_key=req.session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"task_id": task_id}


@router.post("/post-test/generate")
def post_test_generate(req: PostTestRequest, current: dict = Depends(get_current_user)):
    """后测出题（异步）：立即返回 task_id。"""
    _require_llm_ready()
    try:
        model_id = resolve_generation_model(req.generation_model)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    from app.db import SessionLocal
    from app.models import Assessment
    with SessionLocal() as db:
        previous = db.get(Assessment, req.prev_assessment_id)
        if (not previous or previous.user_id != current["uid"] or previous.kind != "pre"
                or record_profile_id(previous) != current_profile_id(db, current["uid"])):
            raise HTTPException(404, "前测记录不存在")
    task_id = enqueue_task("post_generate", {
        "prev_assessment_id": req.prev_assessment_id, "model_id": model_id,
        "profile_id": record_profile_id(previous),
    }, user_id=current["uid"])
    return {"task_id": task_id}


@router.post("/post-test/submit")
def post_test_submit(req: SubmitRequest, current: dict = Depends(get_current_user)):
    """提交后测答案（异步）：立即返回 task_id。"""
    _require_llm_ready()
    parts = req.session_id.split(":", 1)
    session_id = parts[0]
    prev_id = parts[1] if len(parts) > 1 else ""
    session = get_session(session_id, current["uid"])
    if (not session or session["kind"] != "post" or session["prev_assessment_id"] != prev_id
            or not _is_current_profile(current["uid"], session["profile_id"])):
        raise HTTPException(404, "后测会话不存在")

    try:
        task_id = enqueue_task("post_submit", {
            "session_id": session_id, "prev_assessment_id": prev_id,
            "profile_id": session["profile_id"],
            "answers": [item.model_dump() for item in req.answers],
        }, user_id=current["uid"], idempotency_key=session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"task_id": task_id}


# ---------- 用户历史与雷达图 ----------

@router.get("/users/{user_id}/profile-insights")
def user_profile_insights(user_id: str, current: dict = Depends(get_current_user)):
    _require_owner(user_id, current)
    return get_user_profile_insights(user_id)

@router.get("/history/{user_id}")
def history(user_id: str, current: dict = Depends(get_current_user)):
    _require_owner(user_id, current)
    return {"history": get_user_history(user_id)}


@router.get("/archive/{user_id}")
def archive(user_id: str, category: str = "assessments",
            limit: int = Query(12, ge=1, le=50), offset: int = Query(0, ge=0),
            service_id: str = Query("", max_length=32), state: str = Query("", max_length=16),
            q: str = Query("", max_length=80),
            current: dict = Depends(get_current_user)):
    _require_owner(user_id, current)
    try:
        return get_user_archive(user_id, category, limit, offset, service_id, state, q.strip())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/results/{assessment_id}")
def assessment_result(assessment_id: str, current: dict = Depends(get_current_user)):
    """Reload a completed report without relying on browser session storage."""
    _require_record_profile(assessment_id, current["uid"])
    report = load_assessment_result(assessment_id, current["uid"])
    if not report:
        raise HTTPException(404, "测评结果不存在")
    return report


@router.post("/results/{assessment_id}/retry-learning")
def retry_learning_result(assessment_id: str, current: dict = Depends(get_current_user)):
    """Retry only the failed learning workflow; keep the saved score."""
    _require_record_profile(assessment_id, current["uid"])
    report = load_assessment_result(assessment_id, current["uid"])
    if not report or report.kind != "pre":
        raise HTTPException(404, "测评结果不存在")
    if report.plan_review:
        raise HTTPException(409, "学习计划已生成")
    _require_llm_ready()
    task_id = enqueue_task("retry_learning", {"assessment_id": assessment_id,
                                              "profile_id": _current_profile(current["uid"])},
                           user_id=current["uid"], idempotency_key=assessment_id)
    return {"task_id": task_id}


@router.get("/sessions/{session_id}")
def question_session(session_id: str, current: dict = Depends(get_current_user)):
    session = get_session(session_id, current["uid"])
    if not session or not _is_current_profile(current["uid"], session["profile_id"]):
        raise HTTPException(404, "测评会话不存在")
    return {"session_id": session_id, "service_id": session["service_id"],
            "kind": session["kind"], "prev_assessment_id": session["prev_assessment_id"],
            "blueprint": session["blueprint"],
            "questions": public_questions(session["questions"])}


@router.get("/users/{user_id}/track-radar")
def user_track_radar(user_id: str, track_id: str = "big_data", current: dict = Depends(get_current_user)):
    """获取用户在某 Track 下的全服务能力雷达图。"""
    _require_owner(user_id, current)
    if track_id != _current_profile(user_id):
        raise HTTPException(404, "当前 Profile 无此能力档案")
    return get_user_track_radar(user_id, track_id)


@router.get("/team-radar")
def team_radar(track_id: str = "big_data", current: dict = Depends(get_current_user)):
    """获取团队所有 member 在某 Track 下的雷达数据（管理员看板用）。"""
    if current["r"] != "manager":
        raise HTTPException(403, "仅管理员可查看团队数据")
    return {"members": get_team_track_radar(track_id)}


@router.get("/users/{user_id}/pending-post-test")
def user_pending_post_test(user_id: str, service_id: str = "", current: dict = Depends(get_current_user)):
    """查询用户是否有未完成的后测。

    可选 service_id：传则只查该服务，不传只返回 None（跨服务允许并行）。
    """
    _require_owner(user_id, current)
    pending = get_pending_post_test(user_id, service_id or None)
    return {"pending": pending}


@router.get("/users/{user_id}/active-plans")
def user_active_plans(user_id: str, track_id: str = "", current: dict = Depends(get_current_user)):
    """获取用户当前进行中的学习计划（每个 service 最多一条，后测完成后自动消失）。

    可选 track_id：传则只返回该 track 下的 service 的计划。
    """
    _require_owner(user_id, current)
    return {"plans": get_user_active_plans(user_id, track_id=track_id or None)}


def _require_owner(user_id: str, current: dict) -> None:
    if user_id != current["uid"]:
        raise HTTPException(403, "无权访问其他用户的数据")


def _current_profile(user_id: str) -> str | None:
    with SessionLocal() as db:
        return current_profile_id(db, user_id)


def _is_current_profile(user_id: str, profile_id: str | None) -> bool:
    return bool(profile_id and profile_id == _current_profile(user_id))


def _require_record_profile(assessment_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        from app.models import Assessment
        record = db.get(Assessment, assessment_id)
        if not record or record.user_id != user_id or record_profile_id(record) != current_profile_id(db, user_id):
            raise HTTPException(404, "测评结果不存在")
