"""Real-model smoke for a synthetic two-day Glue learning budget.

Run from backend: python -m app.scripts.smoke_flexible_plan
This checks execution and constraints, not expert approval of learning content.
"""
from __future__ import annotations

import argparse
import json

from app.agents.orchestrator import _plan_issues
from app.agents.orchestrator import _critique_issues
from app.agents.planning import run_planning
from app.agents.reflection import run_reflection
from app.schemas.assessment import KnowledgeGap
from app.services.taxonomy import get_service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="deepseek-flash",
        help="Model ID; defaults to the lower-cost DeepSeek Flash model",
    )
    parser.add_argument("--show-plan", action="store_true", help="Print synthetic task text for debugging")
    args = parser.parse_args()
    service = get_service("glue")
    if not service:
        parser.error("Glue taxonomy is unavailable")
    gap = KnowledgeGap(
        gap_id="smoke_nat", capability_id="glue_network", capability_name="网络",
        question_id="synthetic", severity="major", title="VPC 公网出口",
        misunderstanding="以为 Glue VPC ENI 可直接通过 IGW 访问公网",
        correct_understanding="Glue VPC ENI 只有私有 IP，访问公网 API 需要 NAT 等出口",
        evidence_quote="合成测评样本",
    )
    plan, planning_step, _ = run_planning(
        service_name=service["name"], overall_level="L2", capability_scores={},
        gaps=[gap], svc=service, model=args.model, study_days=2, minutes_per_day=45)
    issues = _plan_issues(plan, [gap], study_days=2, minutes_per_day=45)
    critique, review_step = run_reflection(
        gaps=[gap], plan=plan, model=args.model, study_days=2, minutes_per_day=45,
        overall_level="L2")
    quality_gate_status = ("needs_review" if issues or _critique_issues(critique)
                           else "unverified" if review_step.status != "ok" else "passed")
    print(json.dumps({
        "model_id": args.model,
        "planning_status": planning_step.status,
        "review_status": review_step.status,
        "quality_gate_status": quality_gate_status,
        "task_count": sum(len(week.tasks) for week in plan.weekly_plan),
        "task_minutes": [task.time_minutes for week in plan.weekly_plan for task in week.tasks],
        "execution_contracts": [{"day": task.day,
                                  "preconditions": bool(task.preconditions.strip()),
                                  "verification_steps": bool(task.verification_steps.strip()),
                                  "risk_and_cleanup": bool(task.risk_and_cleanup.strip())}
                                 for week in plan.weekly_plan for task in week.tasks],
        "deferred_gap_ids": plan.deferred_gap_ids,
        "deterministic_issues": issues,
        "critique_issue_count": sum(len(critique.get(key, [])) for key in
                                    ("uncovered_gap_ids", "weak_alignment_tasks", "quality_issues")),
    }, ensure_ascii=False, indent=2))
    if args.show_plan:
        print(json.dumps({"assessment": plan.overall_assessment,
                          "tasks": [task.model_dump(include={"day", "topic", "hands_on",
                                                             "preconditions", "verification_steps",
                                                             "risk_and_cleanup"})
                                    for week in plan.weekly_plan for task in week.tasks]},
                         ensure_ascii=False, indent=2))
    return 0 if planning_step.status == "ok" and not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
