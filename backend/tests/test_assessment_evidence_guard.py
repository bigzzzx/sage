"""Agent-authored trials and source-to-capability mismatches must not become ability evidence."""
import unittest
from types import SimpleNamespace

from app.services.assessment import _comparison_for_result
from app.services.assessment_blueprint import build_blueprint
from app.services.question_gen import _validate_questions


class AssessmentEvidenceGuardTests(unittest.TestCase):
    def test_agent_trial_never_reports_growth(self):
        pre = SimpleNamespace(id="pre", user_id="u", service_id="glue", record_origin="user",
                              questions_snapshot=[], question_results=[], created_at=None)
        post = SimpleNamespace(id="post", user_id="u", service_id="glue", kind="post",
                               record_origin="agent_test", questions_snapshot=[], question_results=[],
                               created_at=None)
        comparison = _comparison_for_result(pre, post, "u")
        self.assertFalse(comparison["comparable"])
        self.assertIsNone(comparison["delta"])
        self.assertIn("代答测试", comparison["reason"])

    def test_worker_fact_cannot_be_scored_as_observability(self):
        blueprint = build_blueprint(9)
        questions = []
        for i, ((kind, difficulty), count) in enumerate(blueprint["expected"].items()):
            for j in range(count):
                q = {"id": f"q{i}_{j}", "type": kind, "difficulty": difficulty,
                     "dimension_id": "glue_observability", "question": f"Question {i} {j}?",
                     "source_ids": ["g1x"]}
                if kind == "choice":
                    q.update(options=["a", "b", "c", "d"], correct_answer="A", multi_select=False)
                else:
                    q.update(scoring_rubric=["a", "b", "c"], reference_answer="answer")
                questions.append(q)
        with self.assertRaisesRegex(ValueError, "能力点不匹配"):
            _validate_questions(questions, {"glue_observability"}, {"g1x"}, blueprint)


if __name__ == "__main__":
    unittest.main()
