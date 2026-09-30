"""Focused offline tests for source governance and the bounded review loop."""
from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.agents.diagnosis import _diagnose_one_question, _normalize_glue_understanding, _supported_gaps, run_diagnosis
from app.agents.orchestrator import _plan_issues, run_post_scoring_pipeline
from app.agents.workflow_graph import run_checkpointed
from app.agents.planning import run_planning
from app.agents.reflection import run_reflection
from app.services.glue_sources import load_glue_facts
from app.services.assessment import _score_open_question
from app.schemas.assessment import AgentStep, KnowledgeGap, LearningPlan, LearningTask, WeekPlan
from app.schemas.assessment import GenerateRequest


def _gap() -> KnowledgeGap:
    return KnowledgeGap(gap_id="gap_q1_0", capability_id="glue_network",
                        question_id="q1", severity="critical", title="NAT 出口")


def _plan(name: str, count: int) -> LearningPlan:
    return LearningPlan(plan_name=name, weekly_plan=[WeekPlan(week=1, focus="网络", tasks=[
        LearningTask(day=f"Day {index}", topic="VPC", targets_gap_ids=["gap_q1_0"],
                     objective="识别 Glue 网络出口", hands_on="检查子网路由与 NAT")
        for index in range(1, count + 1)
    ])])


class WorkflowTests(unittest.TestCase):
    def test_study_budget_drives_plan_prompt_and_hard_validation(self) -> None:
        request = GenerateRequest.model_validate(
            {"service_id": "glue", "study_days": 2, "minutes_per_day": 45})
        self.assertEqual((request.study_days, request.minutes_per_day), (2, 45))
        with self.assertRaises(ValueError):
            GenerateRequest.model_validate(
                {"service_id": "glue", "study_days": 0, "minutes_per_day": 45})
        plan_json = {"plan_name": "Two days", "weekly_plan": [{"week": 1, "focus": "network",
            "tasks": [{"day": f"Day {day}", "topic": "VPC",
                       "targets_gap_ids": ["gap_q1_0"], "objective": "掌握 NAT",
                       "hands_on": "检查路由", "time_minutes": 45} for day in (1, 2)]}]}
        # Providers sometimes return the single week as an object despite an array schema.
        plan_json["weekly_plan"] = plan_json["weekly_plan"][0]
        plan_json["priority_dimensions"] = [{"dimension": "network"}]
        plan_json["verification"] = {"method": "post test"}
        with patch("app.agents.planning.get_llm") as llm:
            llm.return_value.chat_traced.return_value = (json.dumps(plan_json), 10)
            plan, _, _ = run_planning("AWS Glue", "L2", {}, [_gap()], {"id": "glue"},
                                      study_days=2, minutes_per_day=45)
            prompt = llm.return_value.chat_traced.call_args.args[0][1]["content"]
        self.assertIn("2 天", prompt)
        self.assertIn("45 分钟", prompt)
        self.assertEqual(plan.priority_dimensions, ["network"])
        self.assertEqual(plan.verification, "post test")
        self.assertEqual(_plan_issues(plan, [_gap()], study_days=2, minutes_per_day=45), [])
        plan.weekly_plan[0].tasks[0].time_minutes = 60
        self.assertTrue(any("45 分钟" in issue for issue in
                            _plan_issues(plan, [_gap()], study_days=2, minutes_per_day=45)))

    def test_reviewer_sees_actual_practice_fields_and_rejects_empty_output(self) -> None:
        plan = _plan("draft", 5)
        plan.weekly_plan[0].tasks[0].hands_on = "检查路由表并验证 NAT 出口"
        plan.weekly_plan[0].tasks[0].troubleshooting = "排查网络超时"
        plan.weekly_plan[0].tasks[0].preconditions = "预置隔离 VPC 与只读权限"
        plan.weekly_plan[0].tasks[0].verification_steps = "同一公网目标前后对照"
        plan.weekly_plan[0].tasks[0].risk_and_cleanup = "不修改生产路由"
        with patch("app.agents.reflection.get_llm") as llm:
            llm.return_value.chat_traced.return_value = ("{}", 10)
            critique, step = run_reflection([_gap()], plan, model="selected-model",
                                            overall_level="L2")
            prompt = llm.return_value.chat_traced.call_args.args[0][1]["content"]
        self.assertIn("检查路由表并验证 NAT 出口", prompt)
        self.assertIn("排查网络超时", prompt)
        self.assertIn("预置隔离 VPC", prompt)
        self.assertIn("同一公网目标前后对照", prompt)
        self.assertIn("L2", prompt)
        self.assertIn("time_minutes", prompt)
        self.assertEqual(critique, {})
        self.assertEqual(step.status, "failed")

    def test_resource_changing_tasks_need_execution_contract(self) -> None:
        plan = _plan("draft", 2)
        task = plan.weekly_plan[0].tasks[0]
        task.hands_on = "创建 NAT 网关并修改路由"
        issues = _plan_issues(plan, [_gap()], study_days=2, minutes_per_day=90)
        self.assertTrue(any("Day 1 实操缺少" in issue for issue in issues))
        task.preconditions = "预置隔离 VPC、IAM 权限与测试预算"
        task.verification_steps = "同一公网 API 修复前后在 Glue 内测试"
        task.risk_and_cleanup = "记录费用，回滚路由并删除测试 NAT"
        self.assertEqual(_plan_issues(plan, [_gap()], study_days=2, minutes_per_day=90), [])
        task.risk_and_cleanup = "无资源变更"
        self.assertTrue(any("声称无资源变更" in issue for issue in
                            _plan_issues(plan, [_gap()], study_days=2, minutes_per_day=90)))
        task.task_type = "reading"
        task.hands_on = "只读检查路由，不要创建 NAT，也不修改现有路由"
        self.assertEqual(_plan_issues(plan, [_gap()], study_days=2, minutes_per_day=90), [])

    def test_public_api_does_not_accept_s3_endpoint_as_nat_alternative(self) -> None:
        gap = _gap()
        gap.correct_understanding = "Glue 访问公网 API 需要 NAT 出口"
        plan = _plan("draft", 2)
        plan.overall_assessment = "公网 API 不通，需 NAT 网关或 S3 VPC Endpoint。"
        issues = _plan_issues(plan, [gap], study_days=2, minutes_per_day=90)
        self.assertTrue(any("S3 Endpoint" in issue for issue in issues))
        plan.overall_assessment = "公网 API 使用 NAT；S3 Endpoint 仅用于 S3 私网访问，不能替代 NAT。"
        self.assertEqual(_plan_issues(plan, [gap], study_days=2, minutes_per_day=90), [])

    def test_graph_resumes_after_planning_failure_without_repeating_diagnosis(self) -> None:
        inputs = dict(service_id="glue", service_name="AWS Glue", svc={"id": "glue"},
                      questions=[], answers_map={}, question_results=[],
                      capability_radar=[], overall_level="L2",
                      enable_reflection=True, model="selected-model")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoints.sqlite"
            with (patch("app.agents.orchestrator.run_diagnosis",
                        return_value=([_gap()], [])) as diagnose,
                  patch("app.agents.orchestrator.run_planning",
                        side_effect=[RuntimeError("interrupted"),
                                     (_plan("resumed", 5), AgentStep(agent="planning"), [])]) as planning,
                  patch("app.agents.orchestrator.run_reflection",
                        return_value=({"overall_score": 5}, AgentStep(agent="reflection")))):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    run_checkpointed(workflow_id="assessment:test:session", checkpoint_path=path,
                                     **inputs)
                result = run_checkpointed(workflow_id="assessment:test:session",
                                          checkpoint_path=path, **inputs)
                cached = run_checkpointed(workflow_id="assessment:test:session",
                                          checkpoint_path=path, **inputs)
            self.assertEqual(diagnose.call_count, 1)
            self.assertEqual(planning.call_count, 2)
            self.assertEqual(result[1].plan_name, "resumed")
            self.assertEqual(result[2]["status"], "passed")
            self.assertEqual(cached[1].plan_name, "resumed")

    def test_graph_matches_legacy_bounded_review_on_fixed_inputs(self) -> None:
        kwargs = dict(service_id="glue", service_name="AWS Glue", svc={"id": "glue"},
                      questions=[], answers_map={}, question_results=[],
                      capability_radar=[], overall_level="L2", model="selected-model")
        outputs = []
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.agents.workflow_graph._checkpoint_path",
                       return_value=Path(directory) / "checkpoints.sqlite"):
                for graph_mode in (False, True):
                    with (patch("app.agents.orchestrator.run_diagnosis",
                                return_value=([_gap()], [])),
                          patch("app.agents.orchestrator.run_planning", side_effect=[
                              (_plan("draft", 1), AgentStep(agent="planning"), []),
                              (_plan("revised", 5), AgentStep(agent="planning"), [])]),
                          patch("app.agents.orchestrator.run_reflection", side_effect=[
                              ({"overall_score": 2, "quality_issues": ["too short"]},
                               AgentStep(agent="reflection")),
                              ({"overall_score": 5}, AgentStep(agent="reflection"))])):
                        result = run_post_scoring_pipeline(
                            **kwargs, workflow_id="assessment:test:parity" if graph_mode else None)
                    outputs.append(result)
        self.assertEqual(outputs[0][1].model_dump(), outputs[1][1].model_dump())
        self.assertEqual(outputs[0][2], outputs[1][2])

    def test_graph_does_not_invent_plan_when_no_supported_gap_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (patch("app.agents.orchestrator.run_diagnosis",
                        return_value=([], [])),
                  patch("app.agents.orchestrator.run_planning") as planning):
                _, plan, review, _, _ = run_checkpointed(
                    workflow_id="assessment:test:no-gap",
                    checkpoint_path=Path(directory) / "checkpoints.sqlite",
                    service_id="glue", service_name="AWS Glue", svc={"id": "glue"},
                    questions=[], answers_map={},
                    question_results=[{"type": "choice", "is_correct": False,
                                       "total_score": 0}],
                    capability_radar=[], overall_level="L1",
                    enable_reflection=True, model="selected-model")
        planning.assert_not_called()
        self.assertEqual(plan.weekly_plan, [])
        self.assertEqual(review["status"], "needs_review")

    def test_partial_diagnosis_failure_cannot_pass_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (patch("app.agents.orchestrator.run_diagnosis",
                        return_value=([_gap()], [AgentStep(agent="diagnosis", status="failed")])),
                  patch("app.agents.orchestrator.run_planning",
                        return_value=(_plan("draft", 5), AgentStep(agent="planning"), [])),
                  patch("app.agents.orchestrator.run_reflection",
                        return_value=({"overall_score": 5}, AgentStep(agent="reflection")))):
                _, _, review, _, _ = run_checkpointed(
                    workflow_id="assessment:test:partial",
                    checkpoint_path=Path(directory) / "checkpoints.sqlite",
                    service_id="glue", service_name="AWS Glue", svc={"id": "glue"},
                    questions=[], answers_map={}, question_results=[],
                    capability_radar=[], overall_level="L2",
                    enable_reflection=True, model="selected-model")
        self.assertEqual(review["status"], "needs_review")
        self.assertTrue(any("诊断失败" in issue for issue in review["remaining_issues"]))

    def test_scoring_and_diagnosis_receive_bound_fact(self) -> None:
        ref = {"id": "vpc_nat", "fact": "Glue VPC ENI 只有私有 IP", "url": "https://docs.aws.amazon.com/example"}
        question = {"type": "open", "difficulty": "L2", "question": "网络出口？",
                    "scoring_rubric": ["出口"], "reference_answer": "NAT", "source_refs": [ref]}
        with patch("app.services.assessment.get_llm") as llm:
            llm.return_value.chat.return_value = json.dumps({"scores": {
                "accuracy": 4, "completeness": 4, "logical_flow": 4, "technical_depth": 4}})
            _score_open_question(question, "NAT", model="selected-model")
            self.assertIn(ref["fact"], llm.return_value.chat.call_args.args[0][1]["content"])
            self.assertEqual(llm.return_value.chat.call_args.kwargs["model"], "selected-model")
        with patch("app.agents.diagnosis.get_llm") as llm:
            llm.return_value.chat_traced.return_value = ("[]", 1)
            _diagnose_one_question("Glue", {"id": "glue_network", "name": "网络"},
                                   question, "不知道", 1, "", set(), model="selected-model")
            self.assertIn(ref["fact"], llm.return_value.chat_traced.call_args.args[0][1]["content"])

    def test_glue_planning_uses_curated_facts_from_shared_corpus(self) -> None:
        from app.services.rag import curated_fact_documents
        resolved_url = curated_fact_documents("glue")[0].url
        answer = {"plan_name": "smoke", "weekly_plan": [{"week": 1, "focus": "catalog",
            "tasks": [{"day": "Day 1", "topic": "Crawler", "concepts": [
                {"point": "Catalog metadata", "url": resolved_url},
                {"point": "Unsupported reference", "url": "https://docs.aws.amazon.com/glue/latest/dg/missing.html"}]}]}]}
        with (patch("app.agents.planning.retrieve_resources", return_value=[]) as retrieve,
              patch("app.agents.planning.get_llm") as llm):
            llm.return_value.chat_traced.return_value = (json.dumps(answer), 1)
            plan, _, sources = run_planning("AWS Glue", "L2", {}, [],
                                            {"id": "glue", "capabilities": []}, model="selected-model")
        self.assertEqual(plan.weekly_plan[0].tasks[0].concepts[0]["url"], resolved_url)
        self.assertEqual(plan.weekly_plan[0].tasks[0].concepts[1]["url"], "")
        self.assertEqual(sources[0]["retrieval_method"], "curated")
        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(llm.return_value.chat_traced.call_args.kwargs["model"], "selected-model")

    def test_glue_diagnosis_uses_curated_facts_and_selected_model(self) -> None:
        service = {"capabilities": [{"id": "glue_network", "name": "网络", "doc_refs": []}]}
        with patch("app.agents.diagnosis._diagnose_one_question", return_value=([], 1)) as diagnose:
            run_diagnosis("glue", "AWS Glue", service,
                          [{"id": "q1", "dimension_id": "glue_network", "type": "open", "question": "?"}],
                          {"q1": "不知道"}, [{"question_id": "q1", "total_score": 0}],
                          model="selected-model")
        kwargs = diagnose.call_args.kwargs
        self.assertIn("crawler_catalog", kwargs["checklist_text"])
        self.assertNotIn("START_CRAWL", kwargs["checklist_text"])
        self.assertEqual(kwargs["model"], "selected-model")

    def test_diagnosis_rejects_unasked_omission_and_invented_quote(self) -> None:
        question = {"question": "Glue VPC Job 为何无法访问公网 API？",
                    "reference_answer": "ENI 仅私有 IP，检查 NAT 路由。",
                    "scoring_rubric": ["解释 ENI", "区分 S3 endpoint"]}
        raw = [
            {"title": "S3 Endpoint", "misunderstanding": "未区分 S3 私网路径",
             "correct_understanding": "S3 可以使用 VPC Endpoint", "evidence_quote": "未提及"},
            {"title": "NAT 路由", "misunderstanding": "未检查 NAT 路由",
             "correct_understanding": "检查 NAT 路由", "evidence_quote": "未提及"},
            {"title": "ENI", "misunderstanding": "ENI 有公网 IP",
             "correct_understanding": "ENI 无公网 IP", "evidence_quote": "ENI 有公网 IP"},
            {"title": "编造", "evidence_quote": "用户从未说过的话"},
        ]
        kept = _supported_gaps(raw, question, "ENI 有公网 IP")
        self.assertEqual([item["title"] for item in kept], ["NAT 路由", "ENI"])

    def test_glue_understanding_does_not_claim_one_exclusive_tool(self) -> None:
        original = "Crawler 不负责清洗，清洗转换必须由 Glue ETL Job 完成"
        self.assertEqual(_normalize_glue_understanding(original),
                         "Crawler 不负责清洗，清洗转换可由转换工具（例如 Glue ETL Job）完成")

    def test_review_revises_once_and_passes_model_to_every_stage(self) -> None:
        step = AgentStep(agent="planning")
        review_step = AgentStep(agent="reflection")
        with (patch("app.agents.orchestrator.run_diagnosis", return_value=([_gap()], [])) as diagnose,
              patch("app.agents.orchestrator.run_planning", side_effect=[
                  (_plan("draft", 1), step, []), (_plan("revised", 5), step, [])]) as planning,
              patch("app.agents.orchestrator.run_reflection", side_effect=[
                  ({"overall_score": 2, "quality_issues": [{"issue": "too short"}]}, review_step),
                  ({"overall_score": 5}, review_step)]) as reflection):
            _, plan, review, trace, _ = run_post_scoring_pipeline(
                service_id="glue", service_name="AWS Glue", svc={"id": "glue"},
                questions=[], answers_map={}, question_results=[], capability_radar=[],
                overall_level="L2", model="selected-model")
        self.assertEqual(plan.plan_name, "revised")
        self.assertEqual(review["status"], "passed")
        self.assertTrue(review["revision_applied"])
        self.assertEqual(planning.call_count, 2)
        self.assertEqual(reflection.call_count, 2)
        self.assertEqual(diagnose.call_args.kwargs["model"], "selected-model")
        self.assertTrue(all(call.kwargs["model"] == "selected-model" for call in planning.call_args_list))
        self.assertTrue(all(call.kwargs["model"] == "selected-model" for call in reflection.call_args_list))
        self.assertTrue(any(step.label == "根据审查意见修订学习计划" for step in trace))

    def test_failed_revision_keeps_original_and_marks_review_needed(self) -> None:
        draft = _plan("draft", 1)
        with (patch("app.agents.orchestrator.run_diagnosis", return_value=([_gap()], [])),
              patch("app.agents.orchestrator.run_planning", side_effect=[
                  (draft, AgentStep(agent="planning"), []), ValueError("offline")]),
              patch("app.agents.orchestrator.run_reflection", return_value=(
                  {"overall_score": 2}, AgentStep(agent="reflection")))):
            _, plan, review, trace, _ = run_post_scoring_pipeline(
                service_id="glue", service_name="AWS Glue", svc={"id": "glue"},
                questions=[], answers_map={}, question_results=[], capability_radar=[],
                overall_level="L2", model="selected-model")
        self.assertEqual(plan.plan_name, "draft")
        self.assertEqual(review["status"], "needs_review")
        self.assertFalse(review["revision_applied"])
        self.assertTrue(any(step.status == "failed" for step in trace))


if __name__ == "__main__":
    unittest.main()
