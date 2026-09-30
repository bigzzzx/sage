"""Offline checks for the public Glue evaluation fixture."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlparse

FACTS_PATH = Path(__file__).resolve().parents[2] / "data" / "evals" / "glue_public_facts.json"


class GlueQualityFixtureTests(unittest.TestCase):
    def test_generated_glue_question_requires_known_source_id(self) -> None:
        from app.services.question_gen import _validate_questions

        questions = []
        for index, level in enumerate(("L1", "L1", "L2", "L2", "L3", "L3"), start=1):
            questions.append({"id": f"q{index}", "type": "choice", "difficulty": level,
                              "dimension_id": "glue_network", "question": "Q?",
                              "options": ["a", "b", "c", "d"], "correct_answer": "A",
                              "source_ids": ["vpc_nat"]})
        for index, level in enumerate(("L1", "L2", "L3"), start=7):
            questions.append({"id": f"q{index}", "type": "open", "difficulty": level,
                              "dimension_id": "glue_network", "question": "Q?",
                              "scoring_rubric": ["a", "b", "c"], "reference_answer": "A",
                              "source_ids": ["vpc_nat"]})
        _validate_questions(questions, {"glue_network"}, {"vpc_nat"})
        questions[0]["source_ids"] = ["invented-source"]
        with self.assertRaisesRegex(ValueError, "官方事实来源"):
            _validate_questions(questions, {"glue_network"}, {"vpc_nat"})

    def test_fixture_has_unique_sourced_cases_across_levels(self) -> None:
        facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(facts), 12)
        self.assertEqual(len({item["id"] for item in facts}), len(facts))
        self.assertEqual({item["level"] for item in facts}, {"L1", "L2", "L3"})
        for item in facts:
            with self.subTest(id=item["id"]):
                self.assertEqual(urlparse(item["source"]).hostname, "docs.aws.amazon.com")
                self.assertIn(item["answer"], "ABCD")
                self.assertEqual(len(item["options"]), 4)
                self.assertEqual(len(set(item["options"])), 4)
                self.assertTrue(item["fact"].strip())


if __name__ == "__main__":
    unittest.main()
