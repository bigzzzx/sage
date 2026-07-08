"""测评业务编排服务（v4 - Multi-Agent 流水线）。

v4 变化：
- 评分阶段保留（_score_open_question 给开放题打分）
- 评分完成后调用 agents.orchestrator 跑诊断 → 规划 → 反思 → 收集 trace
- run_assessment 返回的 AssessmentResult 携带 diagnosis + agent_trace 给前端展示
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.common import safe_json_loads, strip_code_fence
from app.agents.orchestrator import run_post_scoring_pipeline
from app.db import SessionLocal
from app.models import Assessment
from app.schemas.assessment import (
    AgentStep,
    AssessmentResult,
    CapabilityScore,
    KnowledgeGap,
    LearningPlan,
    QuestionResult,
    ScoreDetail,
)
from app.services.llm import get_llm
from app.services.question_gen import get_session
from app.services.taxonomy import get_full_taxonomy, get_service


# ---------- LLM 评分 ----------

_SCORING_PROMPT_L1 = """你是 AWS 服务方向的资深 SE，评估以下 L1（基础概念）级别题目的回答。

# 评分维度（3 个维度，每个 1~5 分）

1. **accuracy（准确性）**：回答的内容是否正确
   - 5分：完全正确，无事实错误
   - 3分：大方向对，但有 1~2 处不准确
   - 1分：核心概念错误或答非所问

2. **completeness（完整性）**：是否覆盖了评分要点中的关键信息
   - 5分：覆盖所有评分要点
   - 3分：覆盖一半左右
   - 1分：几乎没覆盖

3. **clarity（表达清晰度）**：回答是否有逻辑、条理清楚、容易理解
   - 5分：层次分明，表述简洁准确
   - 3分：能看懂，但组织稍乱
   - 1分：混乱、难以理解

题目：{question}
评分要点：{rubric}
参考答案：{reference}
SE 回答：{answer}

输出严格 JSON：
{{"scores":{{"accuracy":<1-5>,"completeness":<1-5>,"clarity":<1-5>}},"avg_score":<三项平均保留1位小数>,"level":"L1"或"L2"或"L3","feedback":"80字内，指出具体缺了什么或错在哪"}}
"""

_SCORING_PROMPT_L2 = """你是 AWS 服务方向的资深 SE，评估以下 L2（流程/架构）级别题目的回答。

# 评分维度（4 个维度，每个 1~5 分）

1. **accuracy（准确性）**：回答的内容是否正确
   - 5分：完全正确，无事实错误
   - 3分：大方向对，但有 1~2 处不准确
   - 1分：核心概念错误

2. **completeness（完整性）**：是否覆盖了评分要点
   - 5分：覆盖所有要点
   - 3分：覆盖一半左右
   - 1分：几乎没覆盖

3. **logical_flow（逻辑条理）**：回答是否有清晰的流程/步骤/因果关系
   - 5分：流程完整、因果清晰、有先后顺序
   - 3分：有一定逻辑但不够连贯
   - 1分：毫无条理，东拼西凑

4. **technical_depth（技术深度）**：是否触及原理层面，而不是只说表面
   - 5分：深入到"为什么这样设计"或"底层如何实现"
   - 3分：能描述"是什么"但不解释"为什么"
   - 1分：纯粹表面描述，没有任何技术含量

题目：{question}
评分要点：{rubric}
参考答案：{reference}
SE 回答：{answer}

输出严格 JSON：
{{"scores":{{"accuracy":<1-5>,"completeness":<1-5>,"logical_flow":<1-5>,"technical_depth":<1-5>}},"avg_score":<四项平均保留1位小数>,"level":"L1"或"L2"或"L3","feedback":"80字内，指出具体缺了什么或错在哪"}}
"""

_SCORING_PROMPT_L3 = """你是 AWS 服务方向的资深 SE，评估以下 L3（故障排查）级别题目的回答。

# 一个优秀的 L3 故障排查回答应包含以下 7 个要素（按顺序）

1. **系统化排查思路**：从大到小列出排查方向（如：网络 → 权限 → 配置 → 代码），有明确优先级
2. **具体检查手段**：每个方向看什么日志/配置/指标，用什么工具（如"看 CloudWatch /aws/glue/jobs/{{job-name}} ERROR 级别"）
3. **定位过程与证据**：如何从现象缩小到根因，用什么证据排除其他可能（排除法）
4. **根因解释**：为什么这个原因导致了这个现象（因果链清晰）
5. **文档/知识副证**：引用官方文档或已知行为佐证结论（如"根据 AWS 文档，Glue ENI 需要 SG 自引用规则"）
6. **解决方案**：具体修改什么、怎么改、改完如何验证
7. **前后对比**：修改前什么状态 + 为什么不行 → 修改后什么状态 + 为什么行

# 评分维度（5 个维度，每个 1~5 分）

1. **accuracy（准确性）**：提到的技术点是否正确
   - 5分：所有技术细节准确
   - 3分：大部分对，有 1~2 处不准确
   - 1分：关键技术点错误

2. **systematic_approach（排查思路系统性）**：排查是否有层次、有顺序、覆盖多个维度
   - 5分：从多个维度系统排查，有明确优先级，每个方向给出具体检查手段（看什么日志/配置）
   - 3分：提到了 2~3 个方向但缺乏系统性，或只说"看日志"没说看哪个
   - 1分：只提一个方向或毫无章法

3. **root_cause_identification（根因定位）**：是否准确识别根因，并给出定位依据
   - 5分：精准定位根因 + 解释因果链 + 有排除其他可能的推理过程
   - 3分：接近根因但缺乏推理证据
   - 1分：没有定位或定位完全错误

4. **solution_feasibility（方案可行性）**：解决方案是否具体、可执行、有验证方式
   - 5分：方案具体可操作 + 说明如何验证修复成功 + 可引用文档佐证
   - 3分：方向对但不够具体，缺少验证步骤
   - 1分：没有给方案或方案不可行

5. **before_after_clarity（前后对比清晰度）**：是否讲清修复前后的状态差异和本质原因
   - 5分：清晰对比修复前后状态 + 解释本质变化（为什么改了就行了）
   - 3分：提到了修复方法但没有对比说明
   - 1分：完全没有前后对比

题目：{question}
评分要点：{rubric}
参考答案：{reference}
SE 回答：{answer}

输出严格 JSON：
{{"scores":{{"accuracy":<1-5>,"systematic_approach":<1-5>,"root_cause_identification":<1-5>,"solution_feasibility":<1-5>,"before_after_clarity":<1-5>}},"avg_score":<五项平均保留1位小数>,"level":"L1"或"L2"或"L3","feedback":"80字内，指出具体缺了 7 要素中的哪几个"}}
"""


def _score_open_question(question: dict, answer: str) -> dict:
    difficulty = (question.get("difficulty") or "L2").upper()
    if difficulty == "L1":
        template = _SCORING_PROMPT_L1
    elif difficulty == "L3":
        template = _SCORING_PROMPT_L3
    else:
        template = _SCORING_PROMPT_L2

    prompt = template.format(
        question=question["question"],
        rubric=json.dumps(question.get("scoring_rubric", []), ensure_ascii=False),
        reference=question.get("reference_answer", ""),
        answer=answer,
    )
    resp = get_llm().chat(
        [{"role": "system", "content": "严格输出 JSON"}, {"role": "user", "content": prompt}],
        temperature=0.2,
    )
    fallback = {
        "scores": {"accuracy": 1, "completeness": 1},
        "avg_score": 1.0, "level": "L1", "feedback": "AI 评分解析失败",
    }
    parsed = safe_json_loads(resp, fallback)
    if not isinstance(parsed, dict):
        parsed = fallback
    # 兼容：确保有 avg_score（归一到 0~5）
    if "avg_score" not in parsed and "scores" in parsed:
        scores = parsed["scores"]
        if scores:
            parsed["avg_score"] = round(sum(scores.values()) / len(scores), 1)
        else:
            parsed["avg_score"] = 1.0
    # 兼容旧字段：total_score（部分逻辑仍引用）
    if "total_score" not in parsed:
        parsed["total_score"] = round(parsed.get("avg_score", 1.0) * 5, 1)
    return parsed


# ---------- 主编排 ----------

def run_assessment(
    user_id: str,
    answer_items: list,
    session_id: str = "",
    kind: str = "pre",
    prev_assessment_id: str | None = None,
) -> AssessmentResult:
    """对一次测评打分 + 跑 agent 流水线 + 保存 + 返回。"""

    session = get_session(session_id) if session_id else None
    if not session:
        raise ValueError("无效的 session_id，请重新生成题目")

    service_id = session["service_id"]
    questions = session["questions"]
    svc = get_service(service_id) or {}
    service_name = svc.get("name", service_id)
    cap_id_to_name = {c["id"]: c["name"] for c in svc.get("capabilities", [])}

    answers_map = {a.question_id: a.answer for a in answer_items}

    # ---------- 评分阶段 ----------
    question_results: list[QuestionResult] = []
    cap_agg: dict[str, dict[str, list]] = {}  # capability_id -> {scores: []}

    for q in questions:
        qid = q["id"]
        qtype = q["type"]
        cap_id = q.get("dimension_id", "unknown")
        if cap_id not in cap_agg:
            cap_agg[cap_id] = {"scores": []}

        ans = answers_map.get(qid, "")

        if qtype == "choice":
            correct = (q.get("correct_answer", "") or "").strip().upper()
            user = (ans or "").strip().upper()
            is_correct = user == correct
            score_5 = 5.0 if is_correct else 0.0
            cap_agg[cap_id]["scores"].append(score_5)
            question_results.append(QuestionResult(
                question_id=qid, type="choice", is_correct=is_correct,
                total_score=score_5, feedback="" if is_correct else f"正确答案是 {correct}",
            ))
        elif qtype == "open":
            if not ans.strip():
                question_results.append(QuestionResult(
                    question_id=qid, type="open", score_detail=ScoreDetail(),
                    total_score=0, level="L1", feedback="未作答",
                ))
                cap_agg[cap_id]["scores"].append(0.0)
                continue
            scored = _score_open_question(q, ans)
            scores = scored.get("scores", {})
            sd = ScoreDetail(**{k: float(v) for k, v in scores.items() if k in ScoreDetail.model_fields})
            avg_5 = float(scored.get("avg_score", 0)) or (sum(scores.values()) / len(scores) if scores else 0)
            cap_agg[cap_id]["scores"].append(float(avg_5))
            fb = scored.get("feedback", "")
            question_results.append(QuestionResult(
                question_id=qid, type="open", score_detail=sd,
                total_score=float(scored.get("total_score", 0)),
                level=scored.get("level", "L1"), feedback=fb,
            ))

    # ---------- 雷达图 ----------
    capability_radar: list[CapabilityScore] = []
    capability_excluded: list[str] = []
    diagnostic_scores: list[float] = []

    for cap_id, agg in cap_agg.items():
        if not agg["scores"]:
            continue
        sample_count = len(agg["scores"])
        raw_avg = sum(agg["scores"]) / sample_count
        # 单题维度收敛 50%
        if sample_count <= 1:
            adjusted = round(raw_avg * 0.5 + 2.5 * 0.5, 1)
        else:
            adjusted = round(raw_avg, 1)
            diagnostic_scores.append(adjusted)

        cap_name = cap_id_to_name.get(cap_id, cap_id)
        capability_radar.append(CapabilityScore(
            service_id=service_id, service_name=service_name,
            capability_id=cap_id, capability_name=cap_name,
            score=adjusted, sample_count=sample_count,
        ))
        if sample_count <= 1:
            capability_excluded.append(cap_name)

    capability_radar.sort(key=lambda c: c.capability_id)

    if diagnostic_scores:
        overall_avg = sum(diagnostic_scores) / len(diagnostic_scores)
    else:
        overall_avg = sum(c.score for c in capability_radar) / len(capability_radar) if capability_radar else 0
    overall_level = "L1" if overall_avg < 2.5 else ("L2" if overall_avg < 4.0 else "L3")

    choice_total = sum(1 for r in question_results if r.type == "choice")
    choice_correct = sum(1 for r in question_results if r.type == "choice" and r.is_correct)
    choice_score_str = f"{choice_correct}/{choice_total}" if choice_total else "-"

    # ---------- Multi-Agent 流水线（仅前测）----------
    diagnosis: list[KnowledgeGap] = []
    plan: LearningPlan | None = None
    agent_trace: list[AgentStep] = []
    if kind == "pre":
        try:
            diagnosis, plan, _critique, agent_trace = run_post_scoring_pipeline(
                service_id=service_id,
                service_name=service_name,
                svc=svc,
                questions=list(questions),
                answers_map=answers_map,
                question_results=[r.model_dump() for r in question_results],
                capability_radar=capability_radar,
                overall_level=overall_level,
                enable_reflection=True,
            )
        except Exception as e:  # noqa: BLE001
            # 流水线兜底：出错就退化成空诊断 + 空计划，但仍保存测评记录
            from datetime import datetime, timezone
            agent_trace = [AgentStep(
                agent="orchestrator",
                label="多 Agent 流水线",
                output_summary=f"失败：{e}",
                status="failed",
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )]
            plan = LearningPlan(plan_name="学习计划生成失败", overall_assessment="请重试")

    # ---------- 持久化 ----------
    db = SessionLocal()
    try:
        record = Assessment(
            user_id=user_id,
            kind=kind,
            service_id=service_id,
            prev_assessment_id=prev_assessment_id,
            overall_level=overall_level,
            choice_score=choice_score_str,
            overall_avg=round(overall_avg, 2),
            questions_snapshot=list(questions),
            answers=[a.model_dump() for a in answer_items],
            question_results=[r.model_dump() for r in question_results],
            radar=[c.model_dump() for c in capability_radar],
            learning_plan=plan.model_dump() if plan else None,
            diagnosis=[g.model_dump() for g in diagnosis],
            agent_trace=[s.model_dump() for s in agent_trace],
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        assessment_id = record.id
    finally:
        db.close()

    # 后测对比：取前测 capability radar
    prev_capability_radar = None
    if prev_assessment_id:
        db2 = SessionLocal()
        try:
            prev = db2.query(Assessment).filter_by(id=prev_assessment_id).first()
            if prev and prev.radar:
                prev_capability_radar = [CapabilityScore(**c) for c in prev.radar]
        finally:
            db2.close()

    return AssessmentResult(
        assessment_id=assessment_id,
        user_id=user_id,
        kind=kind,
        service_id=service_id,
        service_name=service_name,
        overall_level=overall_level,
        choice_score=choice_score_str,
        capability_radar=capability_radar,
        capability_excluded=capability_excluded,
        questions=list(questions),
        question_results=question_results,
        learning_plan=plan,
        prev_capability_radar=prev_capability_radar,
        diagnosis=diagnosis,
        agent_trace=agent_trace,
    )


# ---------- 测评准入检查（业务规则）----------

def get_pending_post_test(user_id: str, service_id: str | None = None) -> dict | None:
    """检查用户是否有"前测已做但后测未做"的待办。

    规则：
    - 找用户最近一次 pre 测评（如果指定了 service_id，则限定在该服务内）
    - 如果该 pre 测评至今没有对应的 post 测评（用 prev_assessment_id 关联），则视为待办
    - 跨 service 允许并行；只在同一 service 内拦截
    """
    if not service_id:
        return None
    db = SessionLocal()
    try:
        latest_pre = db.query(Assessment).filter_by(
            user_id=user_id, kind="pre", service_id=service_id,
        ).order_by(Assessment.created_at.desc()).first()
        if not latest_pre:
            return None
        post = db.query(Assessment).filter_by(
            user_id=user_id, kind="post", prev_assessment_id=latest_pre.id,
        ).first()
        if post:
            return None
        return {
            "pending_pre_id": latest_pre.id,
            "service_id": latest_pre.service_id,
            "overall_level": latest_pre.overall_level,
            "created_at": latest_pre.created_at.isoformat() if latest_pre.created_at else "",
        }
    finally:
        db.close()


# ---------- 用户级 Track 雷达图 ----------

def get_user_track_radar(user_id: str, track_id: str = "big_data") -> dict:
    """获取用户在某 Track 下的全 Service 雷达图。"""
    full = get_full_taxonomy()
    target_track = next((t for t in full["tracks"] if t["id"] == track_id), None)
    if not target_track:
        return {"track_id": track_id, "track_name": "", "services": []}

    db = SessionLocal()
    try:
        records = db.query(Assessment).filter_by(user_id=user_id).order_by(Assessment.created_at.desc()).all()
        latest_by_service: dict[str, Assessment] = {}
        for r in records:
            if r.service_id and r.service_id not in latest_by_service:
                latest_by_service[r.service_id] = r
    finally:
        db.close()

    services_out = []
    for s in target_track["services"]:
        sid = s["id"]
        latest = latest_by_service.get(sid)
        if latest:
            score = round(latest.overall_avg or 0, 1)
            caps = [CapabilityScore(**c).model_dump() for c in (latest.radar or [])]
            services_out.append({
                "service_id": sid,
                "service_name": s["name"],
                "icon": s.get("icon", ""),
                "score": score,
                "is_tested": True,
                "is_real": s.get("is_real", False),
                "capabilities": caps,
                "last_assessed_at": latest.created_at.isoformat() if latest.created_at else "",
            })
        else:
            services_out.append({
                "service_id": sid,
                "service_name": s["name"],
                "icon": s.get("icon", ""),
                "score": 0,
                "is_tested": False,
                "is_real": s.get("is_real", False),
                "capabilities": [],
                "last_assessed_at": "",
            })

    return {
        "track_id": target_track["id"],
        "track_name": target_track["name"],
        "icon": target_track.get("icon", ""),
        "services": services_out,
    }


# ---------- 进行中的学习计划 ----------

def get_user_active_plans(user_id: str, track_id: str | None = None) -> list[dict]:
    """获取用户当前进行中的学习计划列表。每个 service 最多一条进行中计划。

    可选 track_id：传则只返回该 track 下的 service 的计划。
    """
    full = get_full_taxonomy()
    service_meta: dict[str, dict] = {}
    for t in full.get("tracks", []):
        for s in t.get("services", []):
            service_meta[s["id"]] = {
                "service_id": s["id"],
                "service_name": s.get("name", s["id"]),
                "icon": s.get("icon", ""),
                "track_id": t["id"],
                "track_name": t.get("name", t["id"]),
            }

    # 如果指定了 track_id，只保留该 track 下的 service
    if track_id:
        allowed_services = {sid for sid, meta in service_meta.items() if meta["track_id"] == track_id}
    else:
        allowed_services = None  # 不过滤

    db = SessionLocal()
    try:
        pres = (
            db.query(Assessment)
            .filter_by(user_id=user_id, kind="pre")
            .order_by(Assessment.created_at.desc())
            .all()
        )
        latest_pre_by_service: dict[str, Assessment] = {}
        for r in pres:
            if r.service_id and r.service_id not in latest_pre_by_service:
                latest_pre_by_service[r.service_id] = r

        out: list[dict] = []
        for service_id, pre in latest_pre_by_service.items():
            if not pre.learning_plan:
                continue
            # track 过滤
            if allowed_services is not None and service_id not in allowed_services:
                continue
            post = (
                db.query(Assessment)
                .filter_by(user_id=user_id, kind="post", prev_assessment_id=pre.id)
                .first()
            )
            if post:
                continue
            meta = service_meta.get(service_id, {
                "service_id": service_id, "service_name": service_id,
                "icon": "", "track_id": "", "track_name": "",
            })
            out.append({
                **meta,
                "assessment_id": pre.id,
                "overall_level": pre.overall_level,
                "overall_avg": pre.overall_avg,
                "created_at": pre.created_at.isoformat() if pre.created_at else "",
                "learning_plan": pre.learning_plan,
                "capability_radar": pre.radar or [],
                "diagnosis": pre.diagnosis or [],
            })

        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return out
    finally:
        db.close()


# ---------- 团队雷达（管理员看板用）----------

def get_team_track_radar(track_id: str = "big_data") -> list[dict]:
    """获取所有 member 角色用户在某 Track 下的雷达数据（给管理员看板用）。"""
    from app.models import User

    db = SessionLocal()
    try:
        members = db.query(User).filter_by(role="member").all()
        results = []
        for m in members:
            radar = get_user_track_radar(m.id, track_id)
            # 只返回有至少一项已测评的用户
            has_tested = any(s.get("is_tested") for s in radar.get("services", []))
            results.append({
                "user_id": m.id,
                "username": m.username,
                "display_name": m.display_name,
                "has_tested": has_tested,
                "radar": radar,
            })
        return results
    finally:
        db.close()


# ---------- 历史 ----------

def get_user_history(user_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        records = db.query(Assessment).filter_by(user_id=user_id).order_by(Assessment.created_at.desc()).limit(50).all()
        return [
            {
                "assessment_id": r.id,
                "kind": r.kind,
                "service_id": r.service_id,
                "overall_level": r.overall_level,
                "overall_avg": r.overall_avg,
                "choice_score": r.choice_score,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "prev_assessment_id": r.prev_assessment_id,
            }
            for r in records
        ]
    finally:
        db.close()
