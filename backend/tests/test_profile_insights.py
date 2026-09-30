"""The profile must distinguish evidence, missing observations and incomparable tests."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.profile_insights import _scored_capabilities, _ticket_feedback, _trend


def assessment(assessment_id, questions, results):
    return SimpleNamespace(id=assessment_id, service_id="glue", questions_snapshot=questions,
                           question_results=results, created_at=datetime.now(timezone.utc))


class ProfileInsightsTests(unittest.TestCase):
    def test_capability_scores_only_use_scored_questions(self):
        row = assessment("a", [{"id": "q1", "dimension_id": "c1", "type": "choice"},
                               {"id": "q2", "dimension_id": "c1", "type": "open"},
                               {"id": "q3", "dimension_id": "c2", "type": "open"}],
                         [{"question_id": "q1", "total_score": 5},
                          {"question_id": "q2", "total_score": 10}])
        self.assertEqual(_scored_capabilities(row), {"c1": {"score": 3.5, "sample_count": 2}})

    def test_ticket_zero_is_observed_but_unobserved_is_not(self):
        dimensions = [{"id": "clarification", "score": 0, "not_observed": False},
                      {"id": "evidence", "score": 0, "not_observed": True}]
        row = SimpleNamespace(id="t1", status="closed", report={"scoring_version": "ticket_v3",
                             "dimensions": dimensions})
        values = {item["id"]: item for item in _ticket_feedback([row])}
        self.assertEqual(values["clarification"]["score"], 0)
        self.assertEqual(values["clarification"]["sample_count"], 1)
        self.assertIsNone(values["evidence"]["score"])

    def test_incomparable_pre_post_does_not_show_delta(self):
        questions = [{"id": f"q{i}", "dimension_id": f"c{i % 3}",
                      "difficulty": ("L1", "L2", "L3")[i % 3], "type": "open"}
                     for i in range(12)]
        results = [{"question_id": q["id"], "type": "open", "total_score": 20,
                    "scoring_version": "assessment_v3"} for q in questions]
        pre = assessment("pre", questions, results)
        post = assessment("post", [{**q, "difficulty": "L1"} for q in questions], results)
        trend = _trend(pre, post)
        self.assertFalse(trend["comparable"])
        self.assertIsNone(trend["delta"])
        self.assertIn("覆盖不同", trend["reason"])
        different_items = assessment("post2", [{**q, "question": "另一道生成题"} for q in questions], results)
        different_trend = _trend(pre, different_items)
        self.assertFalse(different_trend["comparable"])
        self.assertIsNone(different_trend["delta"])
        self.assertIn("出题差异", different_trend["reason"])
        same_items = assessment("post3", questions, results)
        self.assertTrue(_trend(pre, same_items)["comparable"])


if __name__ == "__main__":
    unittest.main()
