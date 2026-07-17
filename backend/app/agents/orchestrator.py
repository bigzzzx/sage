"""多 Agent 编排器。

负责把 评分 → 诊断 → 规划 → 反思 串起来，并收集 trace。
评分由 services/assessment.py 完成（已有逻辑），这里负责后续 agent。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.assessment import (
    AgentStep,
    CapabilityScore,
    KnowledgeGap,
    LearningPlan,
)

from .diagnosis import run_diagnosis
from .planning import run_planning
from .reflection import run_reflection


def run_post_scoring_pipeline(
    *,
    service_id: str,
    service_name: str,
    svc: dict,
    questions: list[dict],
    answers_map: dict[str, str],
    question_results: list[dict],
    capability_radar: list[CapabilityScore],
    overall_level: str,
    enable_reflection: bool = True,
) -> tuple[list[KnowledgeGap], LearningPlan, dict, list[AgentStep], list[dict]]:
    """打分完成后跑剩下的 agent 流水线，返回 (盲区列表, 学习计划, 反思 critique, trace)。"""
    trace: list[AgentStep] = [
        AgentStep(
            agent="orchestrator",
            label="启动多 Agent 流水线",
            input_summary=f"service={service_id}, 题目数={len(questions)}",
            output_summary="开始诊断",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    ]

    # 1. 诊断
    gaps, diag_trace = run_diagnosis(
        service_id=service_id,
        service_name=service_name,
        svc=svc,
        questions=questions,
        answers_map=answers_map,
        question_results=question_results,
    )
    trace.extend(diag_trace)

    # 按 severity 优先级排序：critical > major > minor
    severity_rank = {"critical": 0, "major": 1, "minor": 2}
    gaps.sort(key=lambda g: severity_rank.get(g.severity, 3))

    # 2. 规划
    capability_scores_dict = {c.capability_name: c.score for c in capability_radar}
    plan, plan_step, rag_sources = run_planning(
        service_name=service_name,
        overall_level=overall_level,
        capability_scores=capability_scores_dict,
        gaps=gaps,
        svc=svc,
    )
    trace.append(plan_step)

    # 3. 反思（可选，失败不影响计划）
    critique: dict = {}
    if enable_reflection and gaps:
        critique, refl_step = run_reflection(gaps=gaps, plan=plan)
        trace.append(refl_step)

    trace.append(AgentStep(
        agent="orchestrator",
        label="流水线完成",
        input_summary="",
        output_summary=f"识别 {len(gaps)} 个盲区，生成 {sum(len(w.tasks) for w in plan.weekly_plan)} 个学习任务",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ))

    return gaps, plan, critique, trace, rag_sources
