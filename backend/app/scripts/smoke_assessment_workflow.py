"""Real-model assessment smoke test using an isolated temporary database.

Run from backend: python -m app.scripts.smoke_assessment_workflow
Uses the configured API credential but never prints it, prompts or user answers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="deepseek-flash",
        help="Model ID; defaults to the lower-cost DeepSeek Flash model",
    )
    args = parser.parse_args()
    with TemporaryDirectory(prefix="sage-assessment-smoke-") as directory:
        os.environ["SAGE_DATABASE_URL"] = f"sqlite:///{Path(directory) / 'smoke.db'}"
        os.environ["SAGE_WORKFLOW_CHECKPOINT_PATH"] = str(Path(directory) / "checkpoints.sqlite")
        from app.db import engine, init_db
        from app.schemas.assessment import AnswerItem
        from app.services.assessment import load_assessment_result, run_assessment
        from app.services.llm import get_available_models
        from app.services.question_gen import generate_questions

        try:
            if args.model not in get_available_models()["models"]:
                parser.error("model is not available from the configured provider")
            init_db()
            session_id, questions = generate_questions("glue", user_id="smoke-user", model_id=args.model)
            answers = []
            for question in questions:
                if question["type"] == "choice":
                    answer = question["correct_answer"]
                elif question["difficulty"] == "L1":
                    answer = "我还不确定，应该先检查官方文档和实际配置。"
                else:
                    answer = ""
                answers.append(AnswerItem(question_id=question["id"], answer=answer))
            result = run_assessment("smoke-user", answers, session_id)
            reloaded = load_assessment_result(result.assessment_id, "smoke-user")
            if not reloaded or reloaded.model_id != args.model or not reloaded.plan_review:
                raise AssertionError("model selection or review was not persisted")
            if any(not question.get("source_refs") for question in reloaded.questions):
                raise AssertionError("Glue question source references were not persisted")
            print(json.dumps({
                "model_id": reloaded.model_id,
                "question_count": len(reloaded.questions),
                "source_linked_count": sum(bool(question.get("source_refs")) for question in reloaded.questions),
                "gap_count": len(reloaded.diagnosis),
                "plan_task_count": sum(len(week.tasks) for week in reloaded.learning_plan.weekly_plan)
                    if reloaded.learning_plan else 0,
                "review_status": reloaded.plan_review["status"],
                "remaining_issues": reloaded.plan_review["remaining_issues"],
                "revision_attempted": reloaded.plan_review["revision_attempted"],
                "revision_applied": reloaded.plan_review["revision_applied"],
                "trace_steps": [step.agent + ":" + step.status for step in reloaded.agent_trace],
            }, ensure_ascii=False, indent=2))
        finally:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
