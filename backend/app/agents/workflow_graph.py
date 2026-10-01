"""A checkpointed graph for the post-scoring assessment workflow."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.schemas.assessment import AgentStep, CapabilityScore, KnowledgeGap, LearningPlan

CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "sage-workflow-checkpoints.sqlite"


def _checkpoint_path() -> Path:
    override = os.environ.get("SAGE_WORKFLOW_CHECKPOINT_PATH")
    return Path(override) if override else CHECKPOINT_PATH


def get_saved_inputs(workflow_id: str) -> dict | None:
    """Retrieve already scored inputs so a retry does not call the scorer again."""
    path = _checkpoint_path()
    if not path.exists():
        return None
    with SqliteSaver.from_conn_string(str(path)) as saver:
        snapshot = build_graph().compile(checkpointer=saver).get_state(
            {"configurable": {"thread_id": workflow_id}})
    return snapshot.values.get("inputs") if snapshot.values else None


class State(TypedDict, total=False):
    inputs: dict
    gaps: list[dict]
    plan: dict
    sources: list[dict]
    trace: list[dict]
    critique: dict
    reflection_status: str
    deterministic: list[str]
    issues: list[str]
    revision_attempted: bool
    revision_applied: bool
    review: dict
    finished: bool


def _gaps(state: State) -> list[KnowledgeGap]:
    return [KnowledgeGap(**item) for item in state["gaps"]]


def _diagnose(state: State) -> dict:
    from . import orchestrator as business
    data = state["inputs"]
    gaps, trace = business.run_diagnosis(
        service_id=data["service_id"], service_name=data["service_name"],
        svc=data["svc"], questions=data["questions"], answers_map=data["answers_map"],
        question_results=data["question_results"], model=data["model"])
    rank = {"critical": 0, "major": 1, "minor": 2}
    gaps.sort(key=lambda gap: rank.get(gap.severity, 3))
    return {"gaps": [gap.model_dump() for gap in gaps],
            "trace": state["trace"] + [step.model_dump() for step in trace]}


def _planning(state: State) -> dict:
    from . import orchestrator as business
    data = state["inputs"]
    radar = [CapabilityScore(**item) for item in data["capability_radar"]]
    plan, step, sources = business.run_planning(
        service_name=data["service_name"], overall_level=data["overall_level"],
        capability_scores={item.capability_name: item.score for item in radar},
        gaps=_gaps(state), svc=data["svc"], model=data["model"],
        study_days=data["study_days"], minutes_per_day=data["minutes_per_day"])
    return {"plan": plan.model_dump(), "sources": sources,
            "trace": state["trace"] + [step.model_dump()]}


def _review(state: State) -> dict:
    from . import orchestrator as business
    data = state["inputs"]
    plan = LearningPlan(**state["plan"])
    gaps = _gaps(state)
    deterministic = business._plan_issues(
        plan, gaps, study_days=data["study_days"],
        minutes_per_day=data["minutes_per_day"])
    critique, status, trace = {}, "skipped", state["trace"]
    if data["enable_reflection"] and gaps and plan.weekly_plan:
        critique, step = business.run_reflection(
            gaps=gaps, plan=plan, model=data["model"],
            study_days=data["study_days"], minutes_per_day=data["minutes_per_day"],
            overall_level=data["overall_level"])
        status = step.status
        trace = trace + [step.model_dump()]
    return {"deterministic": deterministic, "critique": critique,
            "reflection_status": status,
            "issues": deterministic + business._critique_issues(critique),
            "trace": trace}


def _revise(state: State) -> dict:
    from . import orchestrator as business
    data = state["inputs"]
    gaps = _gaps(state)
    radar = [CapabilityScore(**item) for item in data["capability_radar"]]
    trace = state["trace"]
    result = {"revision_attempted": True}
    try:
        candidate, step, sources = business.run_planning(
            service_name=data["service_name"], overall_level=data["overall_level"],
            capability_scores={item.capability_name: item.score for item in radar},
            gaps=gaps, svc=data["svc"], model=data["model"],
            review_feedback=business._review_feedback(state["issues"], state["critique"]),
            study_days=data["study_days"], minutes_per_day=data["minutes_per_day"])
        step.label = "根据审查意见修订学习计划"
        trace = trace + [step.model_dump()]
        candidate_issues = business._plan_issues(
            candidate, gaps, study_days=data["study_days"],
            minutes_per_day=data["minutes_per_day"])
        if candidate.weekly_plan and len(candidate_issues) <= len(state["deterministic"]):
            critique, status = {}, "skipped"
            if data["enable_reflection"] and gaps:
                critique, step = business.run_reflection(
                    gaps=gaps, plan=candidate, model=data["model"],
                    study_days=data["study_days"],
                    minutes_per_day=data["minutes_per_day"],
                    overall_level=data["overall_level"])
                step.label = "复审修订后的计划"
                status = step.status
                trace = trace + [step.model_dump()]
            old_score = state["critique"].get("overall_score", 0)
            new_score = critique.get("overall_score", 0)
            old_score = old_score if isinstance(old_score, (int, float)) else 0
            new_score = new_score if isinstance(new_score, (int, float)) else 0
            new_issues = candidate_issues + business._critique_issues(critique)
            if (len(new_issues) < len(state["issues"]) or
                    len(new_issues) == len(state["issues"]) and new_score > old_score):
                result.update(plan=candidate.model_dump(), sources=sources,
                              critique=critique, reflection_status=status,
                              deterministic=candidate_issues, issues=new_issues,
                              revision_applied=True)
    except Exception:
        trace = trace + [AgentStep(
            agent="planning", label="修订学习计划", status="failed",
            output_summary="修订失败，保留原计划并标记待人工复核",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ).model_dump()]
    result["trace"] = trace
    return result


def _finish(state: State) -> dict:
    plan = LearningPlan(**state["plan"])
    issues = list(state["issues"])
    if any(item.get("agent") == "diagnosis" and item.get("status") == "failed"
           for item in state["trace"]):
        issues.append("部分题目诊断失败，学习计划可能遗漏知识缺口")
    review = {
        "status": ("needs_review" if issues else
                   "unverified" if state["inputs"]["enable_reflection"] and
                   state["reflection_status"] != "ok" else "passed"),
        "revision_attempted": state.get("revision_attempted", False),
        "revision_applied": state.get("revision_applied", False),
        "deterministic_issues": state["deterministic"],
        "remaining_issues": issues, "critique": state["critique"],
    }
    step = AgentStep(
        agent="orchestrator", label="流水线完成",
        output_summary=f"识别 {len(state['gaps'])} 个盲区，生成 {sum(len(w.tasks) for w in plan.weekly_plan)} 个学习任务",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return {"review": review, "trace": state["trace"] + [step.model_dump()],
            "finished": True}


def _finish_without_gaps(state: State) -> dict:
    results = state["inputs"]["question_results"]
    has_low_result = any(
        item.get("is_correct") is False if item.get("type") == "choice"
        else float(item.get("total_score", 0)) < 20
        for item in results)
    diagnosis_failed = any(item.get("agent") == "diagnosis" and
                           item.get("status") == "failed" for item in state["trace"])
    issues = (["存在低分或诊断失败，但没有足够证据形成知识缺口"]
              if has_low_result or diagnosis_failed else [])
    review = {"status": "needs_review" if issues else "passed",
              "revision_attempted": False, "revision_applied": False,
              "deterministic_issues": [], "remaining_issues": issues, "critique": {}}
    step = AgentStep(
        agent="orchestrator", label="流水线完成",
        output_summary="未形成有证据支持的知识缺口；未生成补弱计划",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return {"plan": LearningPlan().model_dump(), "sources": [],
            "review": review, "trace": state["trace"] + [step.model_dump()],
            "finished": True}


def build_graph():
    graph = StateGraph(State)
    for name, action in (("diagnose", _diagnose), ("planning", _planning),
                         ("review", _review), ("revise", _revise), ("finish", _finish),
                         ("finish_without_gaps", _finish_without_gaps)):
        graph.add_node(name, action)
    graph.add_edge(START, "diagnose")
    graph.add_conditional_edges("diagnose", lambda state:
                                "planning" if state["gaps"] else "finish_without_gaps")
    graph.add_edge("planning", "review")
    graph.add_conditional_edges("review", lambda state: "revise" if state["issues"] else "finish")
    graph.add_edge("revise", "finish")
    graph.add_edge("finish", END)
    graph.add_edge("finish_without_gaps", END)
    return graph


def run_checkpointed(*, workflow_id: str, checkpoint_path: Path | None = None, **inputs):
    """Resume the same session after interruption, or reuse its completed checkpoint."""
    inputs.setdefault("study_days", 5)
    inputs.setdefault("minutes_per_day", 90)
    path = checkpoint_path or _checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {"configurable": {"thread_id": workflow_id}}
    with SqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph().compile(checkpointer=saver)
        snapshot = graph.get_state(config)
        if snapshot.values:
            if snapshot.values.get("inputs") != inputs:
                raise ValueError("测评工作流参数与已保存的检查点不一致")
            result = (snapshot.values if snapshot.values.get("finished")
                      else graph.invoke(None, config=config))
        else:
            step = AgentStep(
                agent="orchestrator", label="启动多 Agent 流水线",
                input_summary=f"service={inputs['service_id']}, 题目数={len(inputs['questions'])}",
                output_summary="开始诊断",
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            result = graph.invoke({"inputs": inputs, "trace": [step.model_dump()],
                                   "revision_attempted": False,
                                   "revision_applied": False}, config=config)
    return ([KnowledgeGap(**item) for item in result["gaps"]],
            LearningPlan(**result["plan"]), result["review"],
            [AgentStep(**item) for item in result["trace"]], result["sources"])
