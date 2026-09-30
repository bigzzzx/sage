"""Regressions from a real six-question Glue report; run after DB fixtures."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agents.diagnosis import run_diagnosis
from app.agents.orchestrator import _plan_issues
from app.schemas.assessment import LearningPlan, LearningTask, WeekPlan
from app.services.assessment import _assessment_scoring_version, _present_diagnosis, _present_plan_review, _present_question_results, _score_open_question
from app.services.assessment_summary import summarize_answers
from app.services.report_sources import localize_report_sources
from app.services.assessment_fact_checks import false_g4x_explanation


class ReportQualityRegressions(unittest.TestCase):
    def test_scoring_version_keeps_old_reports_distinct(self) -> None:
        old = [{"type": "open", "scoring_version": "assessment_v2"}]
        new = [{"type": "open", "scoring_version": "assessment_v3"}]
        self.assertEqual(_assessment_scoring_version(old), "assessment_v2")
        self.assertEqual(_assessment_scoring_version(new), "assessment_v3")

    def test_correct_but_incomplete_answer_keeps_accuracy_without_high_total(self) -> None:
        question = {"question": "Crawler 是否清洗数据并输出新文件？", "difficulty": "L1",
                    "scoring_rubric": ["解释 Crawler 作用", "说明独立转换作业"],
                    "reference_answer": "Crawler 只建立元数据，转换由独立作业完成"}
        fake = '{"scores":{"accuracy":5,"completeness":2,"clarity":4},"feedback":"缺独立转换做法"}'
        with patch("app.services.assessment.get_llm") as llm:
            llm.return_value.chat.return_value = fake
            scored = _score_open_question(question, "Crawler 创建 Catalog 表")
        self.assertEqual(scored["scores"]["accuracy"], 5)
        self.assertEqual(scored["avg_score"], 3.0)
        self.assertIn("遗漏只影响完整性", llm.return_value.chat.call_args.args[0][1]["content"])

    def test_all_questions_count_and_small_sample_has_no_level(self) -> None:
        questions = [{"id": f"q{i}", "type": "choice" if i <= 4 else "open",
                      "dimension_id": f"cap{i % 3}"} for i in range(1, 7)]
        results = [{"question_id": f"q{i}", "total_score": score}
                   for i, score in enumerate((5, 5, 0, 0, 21.5, 21), 1)]
        summary = summarize_answers(questions, results)
        self.assertAlmostEqual(summary["overall_avg"], 3.08, places=2)
        self.assertFalse(summary["rating_reliable"])
        self.assertEqual(summary["question_count"], 6)
        questions += [{"id": f"q{i}", "type": "choice", "dimension_id": f"cap{i % 3}"}
                      for i in range(7, 13)]
        results += [{"question_id": f"q{i}", "total_score": 5} for i in range(7, 13)]
        questions[4]["difficulty"] = "L3"
        questions[5]["difficulty"] = "L2"
        questions[6]["difficulty"] = "L3"
        self.assertTrue(summarize_answers(questions, results)["rating_reliable"])

    def test_basic_questions_cannot_certify_advanced_ability(self) -> None:
        questions = [{"id": f"q{i}", "type": "choice", "difficulty": "L1",
                      "dimension_id": f"cap{i % 3}"} for i in range(12)]
        results = [{"question_id": f"q{i}", "total_score": 5} for i in range(12)]
        summary = summarize_answers(questions, results)
        self.assertEqual(summary["overall_avg"], 5)
        self.assertEqual(summary["overall_level"], "L1")
        self.assertFalse(summary["rating_reliable"])

    def test_advanced_level_needs_good_advanced_open_answer(self) -> None:
        questions = [{"id": f"q{i}", "type": "open" if i == 11 else "choice",
                      "difficulty": "L3" if i >= 10 else "L2",
                      "dimension_id": f"cap{i % 3}"} for i in range(12)]
        results = [{"question_id": f"q{i}", "total_score": 15 if i == 11 else 5}
                   for i in range(12)]
        summary = summarize_answers(questions, results)
        self.assertEqual(summary["overall_avg"], 4.83)
        self.assertEqual(summary["overall_level"], "L2")
        self.assertTrue(summary["rating_reliable"])

    def test_wrong_choice_uses_selected_text_without_model_guess(self) -> None:
        question = {"id": "q3", "type": "choice", "dimension_id": "glue_test",
                    "options": ["first", "second", "third", "fourth"],
                    "correct_answer": "A", "source_refs": []}
        with patch("app.agents.diagnosis._diagnose_one_question") as model:
            gaps, _ = run_diagnosis("glue", "Glue", {"capabilities": []},
                                    [question], {"q3": "C"},
                                    [{"question_id": "q3", "is_correct": False}])
        model.assert_not_called()
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].misunderstanding, "本题选择 C：third")
        self.assertEqual(gaps[0].correct_understanding, "正确选项 A：first")
        self.assertEqual(gaps[0].severity, "minor")
        old = [{"question_id": "q3", "misunderstanding": "猜测用户不懂并发"}]
        presented = _present_diagnosis(old, [question], [{"question_id": "q3", "answer": "C"}])
        self.assertEqual(presented[0]["misunderstanding"], "本题选择 C：third")
        self.assertEqual(old[0]["misunderstanding"], "猜测用户不懂并发")

    def test_review_rejects_unlinked_claim_and_inevitable_duplicate(self) -> None:
        task = LearningTask(day="Day 1", topic="bookmark", objective="verify", hands_on="read logs",
                            concepts=[{"point": "bookmark 并发", "url": ""}],
                            verification_steps="bookmark 并发后输出出现重复", time_minutes=60)
        plan = LearningPlan(weekly_plan=[WeekPlan(week=1, focus="bookmark", tasks=[task])])
        issues = _plan_issues(plan, [], study_days=1, minutes_per_day=60)
        self.assertTrue(any("官方文档" in issue for issue in issues))
        self.assertTrue(any("必然结果" in issue for issue in issues))

    def test_localized_links_do_not_mutate_saved_report(self) -> None:
        url = "https://docs.aws.amazon.com/glue/latest/dg/add-classifier.html"
        cn = "https://docs.amazonaws.cn/glue/latest/dg/add-classifier.html"
        questions = [{"source_refs": [{"url": url}]}]
        plan = {"weekly_plan": [{"tasks": [{"concepts": [{"url": url}]}]}]}
        gaps = [{"suggested_doc_urls": [url]}]
        sources = [{"url": url}]
        with patch("app.services.report_sources.preferred_official_source", return_value=(cn, "text")) as resolver:
            result = localize_report_sources(questions, plan, gaps, sources)
        resolver.assert_called_once_with(url)
        self.assertEqual(result[0][0]["source_refs"][0]["url"], cn)
        self.assertEqual(result[1]["weekly_plan"][0]["tasks"][0]["concepts"][0]["url"], cn)
        self.assertEqual(result[2][0]["suggested_doc_urls"], [cn])
        self.assertEqual(result[3][0]["url"], cn)
        self.assertEqual(questions[0]["source_refs"][0]["url"], url)

    def test_classifier_false_claim_is_flagged_even_when_rubric_omits_it(self) -> None:
        question = {"question": "分类器顺序？", "difficulty": "L2", "source_ids": ["classifier_order"],
                    "scoring_rubric": [], "reference_answer": "先自定义后内置"}
        answer = "置信度大于 0 即停止后续尝试。"
        fake = '{"scores":{"accuracy":5,"completeness":5,"logical_flow":5,"technical_depth":5},"feedback":"很好"}'
        with patch("app.services.assessment.get_llm") as llm:
            llm.return_value.chat.return_value = fake
            scored = _score_open_question(question, answer)
        self.assertEqual(scored["scores"]["accuracy"], 3)
        self.assertEqual(scored["total_score"], 21)
        self.assertIn("certainty=1.0", scored["feedback"])
        old = [{"question_id": "q06", "feedback": "分类器顺序正确", "total_score": 21}]
        displayed = _present_question_results([{**question, "id": "q06"}],
                                              [{"question_id": "q06", "answer": answer}], old)
        self.assertIn("历史评分未追溯修改", displayed[0]["feedback"])
        self.assertEqual(old[0]["feedback"], "分类器顺序正确")

    def test_wrong_technical_answer_cannot_be_rescued_by_style(self) -> None:
        question = {"question": "如何定位 Glue 故障？", "difficulty": "L3",
                    "scoring_rubric": ["根因", "排查", "验证"], "reference_answer": "检查证据"}
        fake = '{"scores":{"accuracy":1,"systematic_approach":5,"root_cause_identification":5,"solution_feasibility":5,"before_after_clarity":5},"feedback":"技术判断错误"}'
        with patch("app.services.assessment.get_llm") as llm:
            llm.return_value.chat.return_value = fake
            scored = _score_open_question(question, "错误但很长的回答")
        self.assertEqual(scored["avg_score"], 2.5)

    def test_g4x_is_not_dismissed_as_nonexistent_worker(self) -> None:
        question = {"type": "choice", "options": ["4 vCPU 和 16 GB", "8 vCPU 和 32 GB",
                                                 "2 vCPU 和 8 GB", "16 vCPU 和 64 GB"],
                    "explanation": "选项 C、D 都不是 Glue worker 的公开规格。"}
        self.assertTrue(false_g4x_explanation(question))
        question["explanation"] = "选项 D 是 G.4X，仍不是本题所问的 G.1X。"
        self.assertFalse(false_g4x_explanation(question))

    def test_old_review_shows_actual_issues_instead_of_generic_message(self) -> None:
        old = {"status": "needs_review", "remaining_issues": ["反思指出计划质量问题"],
               "critique": {"quality_issues": [{"day": "Day 3", "issue": "90 分钟不够"}]}}
        shown = _present_plan_review(old)
        self.assertEqual(shown["remaining_issues"], ["Day 3：90 分钟不够"])
        self.assertEqual(old["remaining_issues"], ["反思指出计划质量问题"])


if __name__ == "__main__":
    unittest.main()
