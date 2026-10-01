"""测评业务编排服务（v4 - Multi-Agent 流水线）。

v4 变化：
- 评分阶段保留（_score_open_question 给开放题打分）
- 评分完成后调用 agents.orchestrator 跑诊断 → 规划 → 反思 → 收集 trace
- run_assessment 返回的 AssessmentResult 携带 diagnosis + agent_trace 给前端展示
"""
from __future__ import annotations

import json
import math
from typing import Any
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

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
from app.services.question_gen import get_session, mismatched_glue_fact_ids
from app.services.assessment_summary import summarize_answers
from app.services.assessment_fact_checks import known_fact_error, false_g4x_explanation
from app.services.report_sources import localize_report_sources
from app.services.taxonomy import get_full_taxonomy, get_service
from app.services.profile_scope import current_profile_id, profile_filter, record_profile_id, service_in_profile


# ---------- LLM 评分 ----------


def _assessment_scoring_version(results: list[dict]) -> str:
    versions = {item.get("scoring_version", "legacy") for item in results
                if item.get("type") == "open"}
    if not versions:
        return "objective_v1"
    if versions == {"assessment_v3"}:
        return "assessment_v3"
    return "assessment_v2" if versions == {"assessment_v2"} else "legacy_or_mixed"

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

# 以下是可参考的 L3 排查要素，并非每题必须按顺序回答的清单；只按题干实际要求评价

1. **系统化排查思路**：从大到小列出排查方向（如：网络 → 权限 → 配置 → 代码），有明确优先级
2. **具体检查手段**：每个方向看什么日志/配置/指标，用什么工具（如"看 CloudWatch /aws/glue/jobs/{{job-name}} ERROR 级别"）
3. **定位过程与证据**：如何从现象缩小到根因，用什么证据排除其他可能（排除法）
4. **根因解释**：为什么这个原因导致了这个现象（因果链清晰）
5. **文档/知识副证**：可用官方文档或已知行为佐证结论；题目未要求引用文档时，不因没有链接扣分
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
{{"scores":{{"accuracy":<1-5>,"systematic_approach":<1-5>,"root_cause_identification":<1-5>,"solution_feasibility":<1-5>,"before_after_clarity":<1-5>}},"avg_score":<五项平均保留1位小数>,"level":"L1"或"L2"或"L3","feedback":"80字内，只指出题目要求但回答缺失的要点或错误事实"}}
"""


def _score_open_question(question: dict, answer: str, *, model: str | None = None) -> dict:
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
    source_refs = question.get("source_refs") or []
    if source_refs:
        evidence = "\n".join(
            f"- [{item.get('id', '')}] {item.get('fact', '')} ({item.get('url', '')})"
            for item in source_refs if isinstance(item, dict)
        )
        prompt += ("\n\n# 已绑定官方事实（仅为来源索引，不代表参考答案已获验证）\n"
                   f"{evidence}\n若参考答案与这些事实冲突，以可核验事实为准；"
                   "用户回答中的技术断言即使不在 rubric 中，若与已绑定事实冲突，也必须降低准确性并在反馈中明确指出；"
                   "仅题干明确要求的要点可以作为完整性扣分依据。"
                   "不要因用户提出有依据的不同解释而扣分。仍须严格输出原定 JSON 格式。")
    prompt += ("\n各维度独立判断；准确性只评回答实际作出的事实断言。正确但简短或遗漏内容的回答，"
               "遗漏只影响完整性及题目要求的过程维度，不得仅因遗漏下调准确性；含错误断言则按错误程度扣准确性。"
               "短而正确的回答不因篇幅短扣分，引用参考答案以外的正确路径也应得分。"
               "没有被题干明确要求的步骤或官方文档引用不得作为扣分项；评分参考资料不是用户必须引用的清单。"
               "accuracy 或根因定位低分时，不得靠表达或篇幅补成高等级；最终加权成绩由系统计算。")
    resp = get_llm().chat(
        [{"role": "system", "content": "严格输出 JSON"}, {"role": "user", "content": prompt}],
        temperature=0.2,
        model=model,
    )
    parsed = safe_json_loads(resp, None)
    required = {
        "L1": {"accuracy", "completeness", "clarity"},
        "L2": {"accuracy", "completeness", "logical_flow", "technical_depth"},
        "L3": {"accuracy", "systematic_approach", "root_cause_identification",
               "solution_feasibility", "before_after_clarity"},
    }[difficulty if difficulty in {"L1", "L2", "L3"} else "L2"]
    if not isinstance(parsed, dict) or not isinstance(parsed.get("scores"), dict):
        raise ValueError("AI 评分无效，请稍后重新提交")
    scores = parsed["scores"]
    if any(key not in scores or isinstance(scores[key], bool)
           or not isinstance(scores[key], (int, float))
           or not math.isfinite(scores[key]) or not 1 <= scores[key] <= 5
           for key in required):
        raise ValueError("AI 评分维度不完整，请稍后重新提交")
    parsed["scores"] = {key: scores[key] for key in required}
    fact_error = known_fact_error(question, answer)
    if fact_error:
        parsed["scores"]["accuracy"] = min(parsed["scores"]["accuracy"], 3)
        parsed["feedback"] = (str(parsed.get("feedback", "")).rstrip("。 ") + "。" + fact_error).strip("。")
    weights = {
        "L1": {"accuracy": 0.5, "completeness": 0.35, "clarity": 0.15},
        "L2": {"accuracy": 0.4, "completeness": 0.25,
               "logical_flow": 0.2, "technical_depth": 0.15},
        "L3": {"accuracy": 0.35, "systematic_approach": 0.2,
               "root_cause_identification": 0.2, "solution_feasibility": 0.15,
               "before_after_clarity": 0.1},
    }[difficulty if difficulty in {"L1", "L2", "L3"} else "L2"]
    weighted = sum(parsed["scores"][key] * weight for key, weight in weights.items())
    if parsed["scores"]["accuracy"] <= 2:
        weighted = min(weighted, 2.5)
    # A true statement that leaves the core question unanswered is not a strong
    # answer. Keep accuracy independent, but cap the overall result when the
    # explicitly requested content is mostly absent.
    if "completeness" in parsed["scores"] and parsed["scores"]["completeness"] <= 2:
        weighted = min(weighted, 2.5 if parsed["scores"]["completeness"] <= 1 else 3.0)
    if difficulty == "L3" and parsed["scores"]["root_cause_identification"] <= 2:
        weighted = min(weighted, 3.0)
    parsed["avg_score"] = round(weighted, 1)
    parsed["total_score"] = round(parsed["avg_score"] * 5, 1)
    parsed["level"] = difficulty
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

    session = get_session(session_id, user_id) if session_id else None
    if not session:
        raise ValueError("无效的 session_id，请重新生成题目")
    if session["kind"] != kind or session["prev_assessment_id"] != prev_assessment_id:
        raise ValueError("测评会话类型或前测记录不匹配")

    with SessionLocal() as db:
        existing = db.query(Assessment).filter_by(session_id=session_id, user_id=user_id).first()
        if existing:
            return load_assessment_result(existing.id, user_id)

    service_id = session["service_id"]
    model_id = session.get("model_id")
    questions = session["questions"]
    svc = get_service(service_id) or {}
    service_name = svc.get("name", service_id)
    cap_id_to_name = {c["id"]: c["name"] for c in svc.get("capabilities", [])}

    answers_map = {a.question_id: a.answer for a in answer_items}
    saved_scoring = None
    if kind == "pre":
        from app.agents.workflow_graph import get_saved_inputs
        saved_scoring = get_saved_inputs(f"assessment:{user_id}:{session_id}")
        if saved_scoring and (saved_scoring["answers_map"] != answers_map or
                              saved_scoring["questions"] != list(questions) or
                              saved_scoring["model"] != model_id):
            raise ValueError("测评会话与已保存的评分检查点不一致")
    saved_results = ({item["question_id"]: item
                      for item in saved_scoring["question_results"]}
                     if saved_scoring else {})

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

        if qid in saved_results:
            prior = QuestionResult(**saved_results[qid])
            question_results.append(prior)
            cap_agg[cap_id]["scores"].append(
                float(prior.total_score) if qtype == "choice"
                else float(prior.total_score) / 5.0)
            continue

        if qtype == "choice":
            correct = (q.get("correct_answer", "") or "").strip().upper()
            user = (ans or "").strip().upper()
            is_correct = user == correct
            score_5 = 5.0 if is_correct else 0.0
            cap_agg[cap_id]["scores"].append(score_5)
            question_results.append(QuestionResult(
                question_id=qid, type="choice", is_correct=is_correct,
                total_score=score_5, feedback="" if is_correct else f"正确答案是 {correct}",
                scoring_version="choice_v1",
            ))
        elif qtype == "open":
            if not ans.strip():
                question_results.append(QuestionResult(
                    question_id=qid, type="open", score_detail=ScoreDetail(),
                    total_score=0, level="L1", feedback="未作答", scoring_version="assessment_v3",
                ))
                cap_agg[cap_id]["scores"].append(0.0)
                continue
            scored = _score_open_question(q, ans, model=model_id)
            scores = scored.get("scores", {})
            sd = ScoreDetail(**{k: float(v) for k, v in scores.items() if k in ScoreDetail.model_fields})
            avg_5 = float(scored.get("avg_score", 0)) or (sum(scores.values()) / len(scores) if scores else 0)
            cap_agg[cap_id]["scores"].append(float(avg_5))
            fb = scored.get("feedback", "")
            question_results.append(QuestionResult(
                question_id=qid, type="open", score_detail=sd,
                total_score=float(scored.get("total_score", 0)),
                level=scored.get("level", "L1"), feedback=fb, scoring_version="assessment_v3",
            ))

    # ---------- 雷达图 ----------
    capability_radar: list[CapabilityScore] = []
    capability_excluded: list[str] = []

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

        cap_name = cap_id_to_name.get(cap_id, cap_id)
        capability_radar.append(CapabilityScore(
            service_id=service_id, service_name=service_name,
            capability_id=cap_id, capability_name=cap_name,
            score=adjusted, sample_count=sample_count,
        ))
        if sample_count <= 1:
            capability_excluded.append(cap_name)

    capability_radar.sort(key=lambda c: c.capability_id)

    summary = summarize_answers(list(questions), [item.model_dump() for item in question_results])
    overall_avg = summary["overall_avg"]
    overall_level = summary["overall_level"]

    choice_total = sum(1 for r in question_results if r.type == "choice")
    choice_correct = sum(1 for r in question_results if r.type == "choice" and r.is_correct)
    choice_score_str = f"{choice_correct}/{choice_total}" if choice_total else "-"

    # ---------- Multi-Agent 流水线（仅前测）----------
    diagnosis: list[KnowledgeGap] = []
    plan: LearningPlan | None = None
    plan_review: dict | None = None
    agent_trace: list[AgentStep] = []
    rag_sources: list[dict] = []
    if kind == "pre":
        try:
            diagnosis, plan, plan_review, agent_trace, rag_sources = run_post_scoring_pipeline(
                service_id=service_id,
                service_name=service_name,
                svc=svc,
                questions=list(questions),
                answers_map=answers_map,
                question_results=[r.model_dump() for r in question_results],
                capability_radar=capability_radar,
                overall_level=overall_level,
                enable_reflection=True,
                model=model_id,
                workflow_id=f"assessment:{user_id}:{session_id}",
                study_days=session.get("study_days", 5),
                minutes_per_day=session.get("minutes_per_day", 90),
            )
        except Exception as e:  # noqa: BLE001
            # Keep valid scores but mark the learning stage as failed, not as a fake plan.
            from datetime import datetime, timezone
            agent_trace = [AgentStep(
                agent="orchestrator",
                label="多 Agent 流水线",
                output_summary=f"失败：{e}",
                status="failed",
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )]
            plan = None
            plan_review = None

    # ---------- 持久化 ----------
    db = SessionLocal()
    try:
        record = Assessment(
            user_id=user_id,
            profile_id=session.get("profile_id"),
            session_id=session_id,
            kind=kind,
            service_id=service_id,
            model_id=model_id,
            prev_assessment_id=prev_assessment_id,
            overall_level=overall_level,
            choice_score=choice_score_str,
            overall_avg=round(overall_avg, 2),
            questions_snapshot=list(questions),
            answers=[a.model_dump() for a in answer_items],
            question_results=[r.model_dump() for r in question_results],
            radar=[c.model_dump() for c in capability_radar],
            learning_plan=plan.model_dump() if plan and plan.weekly_plan else None,
            plan_review=plan_review,
            diagnosis=[g.model_dump() for g in diagnosis],
            agent_trace=[s.model_dump() for s in agent_trace],
            rag_sources=rag_sources,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent submission of the same session may have committed first.
            db.rollback()
            existing = db.query(Assessment).filter_by(session_id=session_id, user_id=user_id).first()
            if existing:
                return load_assessment_result(existing.id, user_id)
            raise
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
        model_id=model_id,
        service_name=service_name,
        blueprint=session.get("blueprint"),
        overall_level=overall_level,
        overall_avg=overall_avg,
        rating_reliable=summary["rating_reliable"],
        rating_reason=summary["rating_reason"],
        scoring_version=_assessment_scoring_version([item.model_dump() for item in question_results]),
        choice_score=choice_score_str,
        answers=answer_items,
        capability_radar=capability_radar,
        capability_excluded=capability_excluded,
        questions=list(questions),
        question_results=question_results,
        learning_plan=plan,
        plan_review=plan_review,
        prev_capability_radar=prev_capability_radar,
        diagnosis=diagnosis,
        agent_trace=agent_trace,
        rag_sources=rag_sources,
    )


def retry_learning(assessment_id: str, user_id: str) -> AssessmentResult:
    """Resume a failed pre-test learning workflow from its saved assessment."""
    with SessionLocal() as db:
        record = db.get(Assessment, assessment_id)
        if not record or record.user_id != user_id or record.kind != "pre":
            raise ValueError("测评记录不存在")
        if record.plan_review:
            return load_assessment_result(assessment_id, user_id)
        session_id, service_id, model_id = record.session_id, record.service_id, record.model_id
        questions, answers = record.questions_snapshot, record.answers
        question_results, radar = record.question_results, record.radar
        level = summarize_answers(questions or [], question_results or [])["overall_level"]
    svc = get_service(service_id) or {}
    session = get_session(session_id, user_id) or {}
    gaps, plan, review, trace, sources = run_post_scoring_pipeline(
        service_id=service_id, service_name=svc.get("name", service_id),
        svc=svc, questions=questions,
        answers_map={item["question_id"]: item["answer"] for item in answers},
        question_results=question_results,
        capability_radar=[CapabilityScore(**item) for item in radar],
        overall_level=level, model=model_id,
        workflow_id=f"assessment:{user_id}:{session_id}",
        study_days=session.get("study_days", 5),
        minutes_per_day=session.get("minutes_per_day", 90),
    )
    with SessionLocal() as db:
        record = db.get(Assessment, assessment_id)
        if not record or record.user_id != user_id:
            raise ValueError("测评记录不存在")
        record.learning_plan = plan.model_dump() if plan.weekly_plan else None
        record.plan_review = review
        record.diagnosis = [item.model_dump() for item in gaps]
        record.agent_trace = [item.model_dump() for item in trace]
        record.rag_sources = sources
        db.commit()
    return load_assessment_result(assessment_id, user_id)


def load_assessment_result(assessment_id: str, user_id: str) -> AssessmentResult | None:
    """Rehydrate an owner-scoped report from its durable assessment snapshot."""
    with SessionLocal() as db:
        record = db.get(Assessment, assessment_id)
        if not record or record.user_id != user_id:
            return None
        previous = db.get(Assessment, record.prev_assessment_id) if record.prev_assessment_id else None
        service = get_service(record.service_id) or {}
        summary = summarize_answers(record.questions_snapshot or [], record.question_results or [])
        display_results = _present_question_results(record.questions_snapshot or [],
                                                     record.answers or [], record.question_results or [])
        from app.models import QuestionSession
        source_session = db.get(QuestionSession, record.session_id) if record.session_id else None
        radar = record.radar or []
        displayed_gaps = _present_diagnosis(record.diagnosis or [], record.questions_snapshot or [],
                                             record.answers or [])
        display_questions, display_plan, displayed_gaps, display_sources = localize_report_sources(
            record.questions_snapshot or [], record.learning_plan,
            displayed_gaps, record.rag_sources or [])
        for question in display_questions:
            if record.service_id == "glue" and mismatched_glue_fact_ids(question):
                question["mapping_warning"] = "该历史题目的官方考点与标注的能力点不匹配；能力点得分仅供审计，不宜据此判断掌握程度。"
            if false_g4x_explanation(question):
                explanation = str(question.get("explanation", ""))
                explanation = explanation.replace("选项 C、D 都不是 Glue worker 的公开规格。", "选项 C 不是 G.1X 规格；选项 D 对应 G.4X（16 vCPU / 64 GB），也是 Glue worker 规格。")
                question["explanation"] = explanation
        return AssessmentResult(
            assessment_id=record.id, user_id=record.user_id, kind=record.kind,
            record_origin=record.record_origin or "user",
            service_id=record.service_id, service_name=service.get("name", record.service_id),
            model_id=record.model_id,
            blueprint=source_session.blueprint if source_session and source_session.user_id == user_id else None,
            overall_level=summary["overall_level"], overall_avg=summary["overall_avg"],
            choice_score=record.choice_score,
            rating_reliable=summary["rating_reliable"],
            rating_reason=summary["rating_reason"],
            scoring_version=_assessment_scoring_version(record.question_results or []),
            answers=record.answers or [],
            capability_radar=radar,
            capability_excluded=[item.get("capability_name", "") for item in radar
                                 if item.get("sample_count", 0) <= 1],
            questions=display_questions,
            question_results=display_results,
            learning_plan=display_plan,
            plan_review=_present_plan_review(record.plan_review),
            prev_capability_radar=previous.radar if previous and previous.user_id == user_id else None,
            comparison=_comparison_for_result(previous, record, user_id),
            diagnosis=displayed_gaps, agent_trace=record.agent_trace or [],
            rag_sources=display_sources,
        )


def _comparison_for_result(previous: Assessment | None, record: Assessment, user_id: str) -> dict | None:
    if not previous or previous.user_id != user_id or record.kind != "post":
        return None
    # Keep the result page and the profile page on the same comparability rule.
    from app.services.profile_insights import _trend
    comparison = _trend(previous, record)
    if record.record_origin == "agent_test" or previous.record_origin == "agent_test":
        comparison["comparable"] = False
        comparison["delta"] = None
        comparison["reason"] = "包含代答测试记录，不能作为用户能力提升证据"
    return comparison


def _present_diagnosis(gaps: list[dict], questions: list[dict], answers: list[dict]) -> list[dict]:
    """Correct old choice reports at read time without rewriting saved evidence."""
    by_question = {q.get("id"): q for q in questions}
    by_answer = {item.get("question_id"): item.get("answer", "") for item in answers}
    presented = []
    for gap in gaps:
        item = dict(gap)
        question = by_question.get(item.get("question_id")) or {}
        if question.get("type") == "choice":
            options = question.get("options") or []
            selected = str(by_answer.get(item.get("question_id"), "")).strip().upper()
            correct = str(question.get("correct_answer", "")).strip().upper()
            if len(selected) == 1 and selected in "ABCD" and len(correct) == 1 and correct in "ABCD" and len(options) == 4:
                item["misunderstanding"] = f"本题选择 {selected}：{options[ord(selected) - 65]}"
                item["correct_understanding"] = f"正确选项 {correct}：{options[ord(correct) - 65]}"
                item["evidence_quote"] = selected
                item["severity"] = "minor"
        presented.append(item)
    return presented


def _present_question_results(questions: list[dict], answers: list[dict], results: list[dict]) -> list[dict]:
    """Flag factual mistakes missed by historical scorers without rewriting stored grades."""
    by_question = {q.get("id"): q for q in questions}
    by_answer = {item.get("question_id"): item.get("answer", "") for item in answers}
    presented = []
    for result in results:
        item = dict(result)
        question = by_question.get(item.get("question_id")) or {}
        error = known_fact_error(question, str(by_answer.get(item.get("question_id"), "")))
        if error and error not in item.get("feedback", ""):
            item["feedback"] = (item.get("feedback", "").rstrip("。 ") +
                                "。历史评分未追溯修改，事实复核提示：" + error).lstrip("。")
        presented.append(item)
    return presented


def _present_plan_review(review: dict | None) -> dict | None:
    """Expand opaque legacy review messages into the saved actionable findings."""
    if not review:
        return review
    presented = dict(review)
    issues = list(review.get("remaining_issues") or [])
    if "反思指出计划质量问题" in issues:
        issues.remove("反思指出计划质量问题")
        for item in (review.get("critique") or {}).get("quality_issues", [])[:6]:
            if isinstance(item, dict):
                issues.append(f"{item.get('day', '')}：{item.get('issue') or item.get('reason') or ''}".strip("："))
            elif item:
                issues.append(str(item))
        if not issues:
            issues = ["旧版审查未留下具体问题，请人工复核学习计划。"]
        presented["remaining_issues"] = issues
    return presented


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
        profile_id = current_profile_id(db, user_id)
        if not service_in_profile(service_id, profile_id):
            return None
        latest_pre = db.query(Assessment).filter_by(
            user_id=user_id, kind="pre", service_id=service_id,
        ).filter(profile_filter(Assessment, profile_id), func.coalesce(Assessment.record_origin, "user") != "agent_test").order_by(Assessment.created_at.desc()).first()
        if not latest_pre:
            return None
        post = db.query(Assessment).filter_by(
            user_id=user_id, kind="post", prev_assessment_id=latest_pre.id,
        ).filter(func.coalesce(Assessment.record_origin, "user") != "agent_test").first()
        if post:
            return None
        return {
            "pending_pre_id": latest_pre.id,
            "service_id": latest_pre.service_id,
            "overall_level": summarize_answers(latest_pre.questions_snapshot or [], latest_pre.question_results or [])["overall_level"],
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
        records = db.query(Assessment).filter_by(user_id=user_id).filter(
            profile_filter(Assessment, track_id), func.coalesce(Assessment.record_origin, "user") != "agent_test").order_by(Assessment.created_at.desc()).all()
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
            summary = summarize_answers(latest.questions_snapshot or [], latest.question_results or [])
            score = round(summary["overall_avg"], 1)
            caps = [CapabilityScore(**c).model_dump() for c in (latest.radar or [])]
            services_out.append({
                "service_id": sid,
                "service_name": s["name"],
                "icon": s.get("icon", ""),
                "score": score,
                "is_tested": True,
                "rating_reliable": summary["rating_reliable"],
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
                "rating_reliable": False,
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
        profile_id = current_profile_id(db, user_id)
        if not profile_id or (track_id and track_id != profile_id):
            return []
        pres = (
            db.query(Assessment)
            .filter_by(user_id=user_id, kind="pre")
            .filter(profile_filter(Assessment, profile_id), func.coalesce(Assessment.record_origin, "user") != "agent_test")
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
                .filter(profile_filter(Assessment, profile_id), func.coalesce(Assessment.record_origin, "user") != "agent_test")
                .first()
            )
            if post:
                continue
            meta = service_meta.get(service_id, {
                "service_id": service_id, "service_name": service_id,
                "icon": "", "track_id": "", "track_name": "",
            })
            summary = summarize_answers(pre.questions_snapshot or [], pre.question_results or [])
            out.append({
                **meta,
                "assessment_id": pre.id,
                "overall_level": summary["overall_level"],
                "overall_avg": summary["overall_avg"],
                "rating_reliable": summary["rating_reliable"],
                "plan_review": pre.plan_review or {},
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
        profile_id = current_profile_id(db, user_id)
        if not profile_id:
            return []
        records = db.query(Assessment).filter_by(user_id=user_id).filter(
            profile_filter(Assessment, profile_id)).order_by(Assessment.created_at.desc()).limit(50).all()
        return [
            {
                "assessment_id": r.id,
                "kind": r.kind,
                "service_id": r.service_id,
                "overall_level": (summary := summarize_answers(r.questions_snapshot or [], r.question_results or []))["overall_level"],
                "overall_avg": summary["overall_avg"],
                "rating_reliable": summary["rating_reliable"],
                "choice_score": r.choice_score,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "prev_assessment_id": r.prev_assessment_id,
                "record_origin": r.record_origin or "user",
            }
            for r in records
        ]
    finally:
        db.close()


def get_user_archive(user_id: str, category: str, limit: int = 12, offset: int = 0,
                     service_id: str = "", state: str = "", query_text: str = "") -> dict:
    """Owner-scoped, paginated assessment and learning-plan summaries."""
    if category not in {"assessments", "plans"}:
        raise ValueError("未知历史类别")
    with SessionLocal() as db:
        profile_id = current_profile_id(db, user_id)
        if not profile_id:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        query = db.query(Assessment).filter(Assessment.user_id == user_id,
                                            profile_filter(Assessment, profile_id))
        if category == "plans":
            query = query.filter(Assessment.kind == "pre",
                                 func.json_type(Assessment.learning_plan) != "null")
        if service_id:
            query = query.filter(Assessment.service_id == service_id)
        if state == "post" and category == "assessments":
            query = query.filter(Assessment.kind == "post")
        elif state == "pre" and category == "assessments":
            query = query.filter(Assessment.kind == "pre")
        elif state == "active" and category == "plans":
            completed_ids = db.query(Assessment.prev_assessment_id).filter(
                Assessment.user_id == user_id, Assessment.kind == "post",
                Assessment.prev_assessment_id.is_not(None),
                profile_filter(Assessment, profile_id)).subquery()
            query = query.filter(~Assessment.id.in_(completed_ids))
        if query_text:
            term = f"%{query_text.lower()}%"
            query = query.filter(Assessment.service_id.ilike(term) |
                                 Assessment.id.ilike(term) |
                                 func.json_extract(Assessment.learning_plan, "$.plan_name").ilike(term))
        total = query.count()
        rows = (query.order_by(Assessment.created_at.desc(), Assessment.id.desc())
                .offset(offset).limit(limit).all())
        items = []
        for row in rows:
            summary = summarize_answers(row.questions_snapshot or [], row.question_results or [])
            item = {"assessment_id": row.id, "service_id": row.service_id,
                    "kind": row.kind, "created_at": row.created_at.isoformat() if row.created_at else "",
                    "overall_level": summary["overall_level"], "overall_avg": summary["overall_avg"],
                    "rating_reliable": summary["rating_reliable"],
                    "record_origin": row.record_origin or "user"}
            if category == "plans":
                completed = db.query(Assessment.id).filter_by(
                    user_id=user_id, kind="post", prev_assessment_id=row.id).filter(
                    profile_filter(Assessment, profile_id), func.coalesce(Assessment.record_origin, "user") != "agent_test").first() is not None
                item.update({"plan_name": (row.learning_plan or {}).get("plan_name", "学习计划"),
                             "status": "completed" if completed else "active",
                             "review_status": (row.plan_review or {}).get("status", "unverified")})
            items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset}
