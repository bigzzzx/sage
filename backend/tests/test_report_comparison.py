"""Offline contracts for the paired quality experiment."""
import json
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scripts.compare_report_strategies import (
    ARMS, DEFAULT_CASES, _review, _reviews_for_arm, _usage_summary, make_blind_template,
    run_case, validate_cases,
)
from app.scripts.score_report_comparison import operational_metrics, score
from app.schemas.assessment import LearningPlan


class ReportComparisonTests(unittest.TestCase):
    def test_reviewer_receives_supplied_level_and_source_policy(self):
        case = json.loads(Path(DEFAULT_CASES).read_text(encoding="utf-8"))[0]
        with patch("app.scripts.compare_report_strategies.get_llm") as llm:
            llm.return_value.chat.return_value = '{"issues": []}'
            _review(case, [], LearningPlan(), "test-model", "general")
            prompt = llm.return_value.chat.call_args.args[0][1]["content"]
        self.assertIn('"overall_level": "L2"', prompt)
        self.assertIn("docs.amazonaws.cn", prompt)
        self.assertIn("S3 VPC Endpoint", prompt)

    def test_fixture_is_well_formed(self):
        validate_cases(json.loads(Path(DEFAULT_CASES).read_text(encoding="utf-8")))

    def test_review_budget_and_debate_information_flow(self):
        calls = []

        def fake_review(case, gaps, plan, model, role, prior=None):
            calls.append((role, prior is not None))
            return {"role": role, "issues": []}

        with patch("app.scripts.compare_report_strategies._review", side_effect=fake_review):
            expected = {"rules": [], "single_review": [("general", False)],
                        "dual_review": [("evidence", False), ("teaching", False)],
                        "debate": [("evidence", False), ("teaching", False),
                                   ("evidence", True), ("teaching", True)],
                        "budget_repeat": [("evidence", False), ("teaching", False),
                                          ("evidence", False), ("teaching", False)]}
            for arm in ARMS:
                calls.clear()
                _reviews_for_arm(arm, {}, [], None, "test")
                self.assertEqual(calls, expected[arm])

    def test_usage_unknown_price_and_missing_token_are_not_zero(self):
        rows = [{"model": "x", "elapsed_ms": 10, "prompt_tokens": 100,
                 "completion_tokens": 20, "status": "ok"}]
        self.assertIsNone(_usage_summary(rows, None, None)["estimated_cost"])
        self.assertEqual(_usage_summary(rows, 1, 2)["estimated_cost"], 0.00014)
        rows.append({"model": "x", "elapsed_ms": 10, "prompt_tokens": None,
                     "completion_tokens": None, "status": "failed"})
        self.assertIsNone(_usage_summary(rows, 1, 2)["prompt_tokens"])

    def test_human_scoring_requires_two_distinct_annotations(self):
        report = {"diagnosis": [], "learning_plan": {}}
        run = {"seed": 1, "complete": True, "cases": [{"case_id": "c", "variants": {
            arm: {"report": report} for arm in ARMS}}]}
        blind = make_blind_template(run["cases"], 1)
        with self.assertRaisesRegex(ValueError, "Two distinct"):
            score(run, blind)
        annotation = {"annotator_id": "a", "labels": {
            "factual_error_count": 0, "diagnosis_error_count": 0,
            "citation_support": 1, "task_actionability": 1}, "evidence_notes": "checked"}
        for row in blind["blind_reports"]:
            row["annotations"] = [annotation, {**annotation, "annotator_id": "b"}]
        result = score(run, blind)
        self.assertEqual(result["status"], "human_labeled")
        self.assertEqual(result["report_count"], len(ARMS))

    def test_runtime_metrics_never_claim_human_quality(self):
        usage = {"api_attempts": 1, "prompt_tokens": 100,
                 "completion_tokens": 25, "estimated_cost": None}
        variant = {"report": {}, "elapsed_ms": 10, "usage": usage,
                   "incremental_usage": usage, "review_calls": 4}
        run = {"model": "m", "complete": True,
               "cases": [{"case_id": "c", "variants": {arm: variant for arm in ARMS}}]}
        result = operational_metrics(run)
        self.assertEqual(result["status"], "runtime_only_not_human_quality")
        self.assertNotIn("mean_labels_by_arm", result)
        self.assertTrue(result["budget_match"][0]["within_20_percent"])

    def test_partial_template_and_resume_reuse_shared_draft(self):
        self.assertEqual(make_blind_template([{"case_id": "failed"}], 1)["blind_reports"], [])
        cases = json.loads(Path(DEFAULT_CASES).read_text(encoding="utf-8"))
        shared_usage = _usage_summary([], None, None)
        previous = {"shared_generation": {
            "diagnosis": [{"gap_id": "g", "capability_id": "glue_network"}],
            "draft": {"weekly_plan": []}, "elapsed_ms": 7, "usage": shared_usage},
            "variants": {"rules": {"report": {"already": "saved"}}}}
        with patch("app.scripts.compare_report_strategies.get_service", return_value={"name": "Glue"}), \
             patch("app.scripts.compare_report_strategies._run_arm", return_value={"report": {}}) as execute:
            result = run_case(cases[0], "model", None, None, previous=previous)
        self.assertEqual(result["variants"]["rules"], previous["variants"]["rules"])
        self.assertEqual(execute.call_count, len(ARMS) - 1)

    def test_ai_audit_is_complete_but_not_human_labels(self):
        audit_path = Path(DEFAULT_CASES).with_name("report_ai_audit_20260926.json")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertIn("not_two_independent_humans", audit["status"])
        self.assertEqual(len(audit["reports"]), 2 * len(ARMS))
        for row in audit["reports"]:
            key = f"{audit['seed']}:{row['case_id']}:{row['arm']}"
            self.assertEqual(row["report_id"], hashlib.sha256(key.encode()).hexdigest()[:16])
            self.assertTrue(row["evidence_notes"])
            self.assertIn(row["labels"]["citation_support"], (0, 1, 2))
            self.assertIn(row["labels"]["task_actionability"], (0, 1, 2))


if __name__ == "__main__":
    unittest.main()
