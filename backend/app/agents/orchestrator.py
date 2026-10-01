"""测评后业务流程及旧版行为基线。

正式前测以 workflow_id 调用 LangGraph；原函数分支保留为迁移对照。
评分由 services/assessment.py 完成。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from app.schemas.assessment import (
    AgentStep,
    CapabilityScore,
    KnowledgeGap,
    LearningPlan,
)

from .diagnosis import run_diagnosis
from .planning import run_planning
from .reflection import run_reflection


def _changes_resources(instructions: str) -> bool:
    """Conservative text signal; negated mentions are not resource changes."""
    for match in re.finditer(r"创建|新建|修改|删除|移除|更改路由|添加路由", instructions):
        prefix = instructions[max(0, match.start() - 7):match.start()]
        if not re.search(r"(?:不|无需|无须|避免|禁止|只读|模拟|推演).{0,3}$", prefix):
            return True
    return False


def _plan_issues(plan: LearningPlan, gaps: list[KnowledgeGap], *,
                 study_days: int = 5, minutes_per_day: int = 90) -> list[str]:
    """Deterministic requirements; an LLM critique alone cannot certify its own plan."""
    issues: list[str] = []
    if len(plan.weekly_plan) != 1:
        issues.append("学习计划必须恰好一周")
    tasks = plan.weekly_plan[0].tasks if plan.weekly_plan else []
    if len(tasks) != study_days or [task.day for task in tasks] != [f"Day {i}" for i in range(1, study_days + 1)]:
        issues.append(f"学习任务必须为 Day 1 至 Day {study_days} 各一项")
    if any(task.time_minutes < 1 or task.time_minutes > minutes_per_day for task in tasks):
        issues.append(f"单日任务时长必须在 1 至 {minutes_per_day} 分钟之间")
    known = {gap.gap_id for gap in gaps}
    cited = {gap_id for task in tasks for gap_id in task.targets_gap_ids}
    if cited - known:
        issues.append("学习任务引用了不存在的盲区")
    if gaps and any(not task.targets_gap_ids for task in tasks):
        issues.append("存在未关联盲区的学习任务")
    if any(not task.objective.strip() or not task.hands_on.strip() for task in tasks):
        issues.append("存在缺少学习目标或实操步骤的任务")
    for task in tasks:
        # A reading task may still create a crawler or change a route. Such work
        # needs the same safety/verification contract as a task labelled "lab".
        changes_resources = _changes_resources(task.hands_on)
        if task.task_type == "lab" or changes_resources:
            missing_fields = [label for label, value in (
                ("前置条件", task.preconditions),
                ("验收步骤", task.verification_steps),
                ("费用风险与清理", task.risk_and_cleanup),
            ) if not value.strip()]
            if missing_fields:
                issues.append(f"{task.day} 实操缺少" + "、".join(missing_fields))
            if changes_resources and "无资源变更" in task.risk_and_cleanup:
                issues.append(f"{task.day} 声称无资源变更，但步骤包含资源创建或修改")
            steps = re.findall(r"(?m)^\s*\d+[.、]", task.hands_on)
            if changes_resources and len(steps) > 6 and task.time_minutes <= 90:
                issues.append(f"{task.day} 在 {task.time_minutes} 分钟内安排了 {len(steps)} 步资源操作；请拆分必做与选做并重新估时")
        for concept in task.concepts:
            if (re.search(r"bookmark|并发|NAT|ENI|公网|classifier", str(concept.get("point", "")), re.I)
                    and not str(concept.get("url", "")).strip()):
                issues.append(f"{task.day} 核心技术结论缺少对应官方文档：{str(concept.get('point', ''))[:50]}")
        if (re.search(r"bookmark.*并发|并发.*bookmark", task.hands_on + task.verification_steps, re.I)
                and re.search(r"输出出现重复|重复消失|必须.*重复", task.verification_steps)):
            issues.append(f"{task.day} 并发 bookmark 实验把重复数据写成必然结果；应允许提交冲突或未复现")
    public_api_gap = any("公网 API" in " ".join((g.title, g.misunderstanding,
                                                 g.correct_understanding))
                         for g in gaps)
    if public_api_gap:
        report_text = "\n".join((plan.overall_assessment, plan.verification,
                                  *(field for task in tasks for field in
                                    (task.objective, task.hands_on,
                                     task.troubleshooting, task.deliverable,
                                     *(str(c.get("point", "")) for c in task.concepts)))))
        for sentence in re.split(r"[。；;\n]", report_text):
            if ("NAT" in sentence.upper() and "或" in sentence and
                    re.search(r"S3\s*(?:VPC\s*)?(?:endpoint|端点)", sentence, re.I) and
                    not any(negation in sentence for negation in
                            ("不能", "不可", "不等于", "不适用", "仅用于", "只用于"))):
                issues.append("公网 API 不能把 S3 Endpoint 当作 NAT 出口替代方案")
                break
    deferred = set(plan.deferred_gap_ids)
    if deferred - known:
        issues.append("延后清单引用了不存在的盲区")
    if deferred & cited:
        issues.append("延后清单包含已经覆盖的盲区")
    missing = sorted(gap.gap_id for gap in gaps
                     if (gap.severity == "critical" and gap.gap_id not in cited) or
                     (gap.severity == "major" and gap.gap_id not in cited and gap.gap_id not in deferred))
    if missing:
        issues.append("未覆盖的重要盲区：" + ", ".join(missing))
    return issues


def _critique_issues(critique: dict) -> list[str]:
    issues: list[str] = []
    score = critique.get("overall_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and score < 4:
        issues.append(f"反思评分 {score}/5")
    for key, label in (("uncovered_gap_ids", "盲区未覆盖"),
                       ("weak_alignment_tasks", "任务与盲区不匹配"),
                       ("quality_issues", "计划质量问题")):
        if isinstance(critique.get(key), list) and critique[key]:
            for item in critique[key][:5]:
                detail = (str(item.get("issue") or item.get("reason") or item)
                          if isinstance(item, dict) else str(item))
                day = str(item.get("day", "")) if isinstance(item, dict) else ""
                issues.append(f"{day} {label}：{detail[:180]}".strip())
    return issues


def _review_feedback(issues: list[str], critique: dict) -> str:
    suggestions = critique.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    return json.dumps({"required_fixes": issues,
                       "suggestions": [str(value)[:180] for value in suggestions[:5]]},
                      ensure_ascii=False)


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
    model: str | None = None,
    workflow_id: str | None = None,
    study_days: int = 5,
    minutes_per_day: int = 90,
) -> tuple[list[KnowledgeGap], LearningPlan, dict, list[AgentStep], list[dict]]:
    """打分完成后跑剩下的 agent 流水线，返回 (盲区列表, 学习计划, 反思 critique, trace)。"""
    if workflow_id is not None:
        from .workflow_graph import run_checkpointed
        return run_checkpointed(
            workflow_id=workflow_id, service_id=service_id, service_name=service_name,
            svc=svc, questions=questions, answers_map=answers_map,
            question_results=question_results,
            capability_radar=[item.model_dump() for item in capability_radar],
            overall_level=overall_level, enable_reflection=enable_reflection, model=model,
            study_days=study_days, minutes_per_day=minutes_per_day)
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
        model=model,
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
        model=model,
    )
    trace.append(plan_step)

    # 3. 审查并最多修订一次；失败时明确标记，不能假装计划通过审核。
    deterministic = _plan_issues(plan, gaps)
    critique: dict = {}
    reflection_status = "skipped"
    if enable_reflection and gaps and plan.weekly_plan:
        critique, refl_step = run_reflection(gaps=gaps, plan=plan, model=model,
                                            overall_level=overall_level)
        reflection_status = refl_step.status
        trace.append(refl_step)
    issues = deterministic + _critique_issues(critique)
    revised = False
    if issues:
        try:
            candidate, revision_step, candidate_sources = run_planning(
                service_name=service_name, overall_level=overall_level,
                capability_scores=capability_scores_dict, gaps=gaps, svc=svc,
                model=model, review_feedback=_review_feedback(issues, critique),
            )
            revision_step.label = "根据审查意见修订学习计划"
            trace.append(revision_step)
            candidate_issues = _plan_issues(candidate, gaps)
            if candidate.weekly_plan and len(candidate_issues) <= len(deterministic):
                candidate_critique: dict = {}
                candidate_status = "skipped"
                if enable_reflection and gaps:
                    candidate_critique, candidate_step = run_reflection(
                        gaps=gaps, plan=candidate, model=model,
                        overall_level=overall_level)
                    candidate_step.label = "复审修订后的计划"
                    candidate_status = candidate_step.status
                    trace.append(candidate_step)
                old_score = critique.get("overall_score", 0)
                new_score = candidate_critique.get("overall_score", 0)
                if not isinstance(old_score, (int, float)):
                    old_score = 0
                if not isinstance(new_score, (int, float)):
                    new_score = 0
                old_issue_count = len(issues)
                new_issue_count = len(candidate_issues) + len(_critique_issues(candidate_critique))
                if (new_issue_count < old_issue_count
                        or new_issue_count == old_issue_count and new_score > old_score):
                    plan, rag_sources = candidate, candidate_sources
                    critique, reflection_status = candidate_critique, candidate_status
                    deterministic = candidate_issues
                    revised = True
        except Exception:  # noqa: BLE001
            trace.append(AgentStep(
                agent="planning", label="修订学习计划", status="failed",
                output_summary="修订失败，保留原计划并标记待人工复核",
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ))

    remaining = deterministic + _critique_issues(critique)
    review = {"status": ("needs_review" if remaining else
                         "unverified" if enable_reflection and reflection_status != "ok"
                         else "passed"),
              "revision_attempted": bool(issues), "revision_applied": revised,
              "deterministic_issues": deterministic, "remaining_issues": remaining,
              "critique": critique}

    trace.append(AgentStep(
        agent="orchestrator",
        label="流水线完成",
        input_summary="",
        output_summary=f"识别 {len(gaps)} 个盲区，生成 {sum(len(w.tasks) for w in plan.weekly_plan)} 个学习任务",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ))

    return gaps, plan, review, trace, rag_sources
