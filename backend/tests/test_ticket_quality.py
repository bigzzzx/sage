"""Behavioral boundaries for reviewed tickets and stateful customer simulation."""
import copy
import json
import unittest
from unittest.mock import patch

from app.services.ticket_quality import (CHECKS, _PageText, build_reviewed_case, fetch_official_excerpt,
                                         official_url_candidates, preferred_official_source,
                                         source_catalog, validate_case)
from app.services.rag import KnowledgeDocument, RetrievedDocument
from app.services.ticket_simulation import PERSONAS, choose_case, get_case, grade_ticket
from app.services.ticket_dialogue import run_customer_turn


def fixture_case():
    return {"title": "训练环境任务运行时间变长", "opening": "训练环境中的任务最近运行时间明显变长，请帮助检查。",
            "controls": {"service_id": "glue", "category": "performance", "difficulty": "intermediate",
                         "impact": "development", "cross_service": False},
            "related_service_ids": [],
            "evidence": [{"id": f"e{i}", "label": f"训练指标{i}", "content": f"模拟任务的指标{i}在相同输入下发生了变化。",
                          "collection_hint": "请打开训练控制台，复制同一作业的运行指标。"} for i in range(4)],
            "expected": {"background": "团队使用训练环境中的 Glue 作业处理每日数据。",
                         "scenario": "相同输入下任务耗时显著高于历史基线。",
                         "problem": "模拟任务运行时间比基线更长。",
                         "investigation_steps": ["确认影响范围和时间线", "对比运行指标和输入", "验证分区分布假设"],
                         "reasoning": "先建立基线，再关联输入和分区指标，以排除单纯数据量增长。",
                         "root_cause": "模拟运行指标表明分区分布存在偏斜。",
                         "resolution": "在训练环境调整分区后对比任务耗时。", "verification": "使用相同输入检查任务耗时和正确性。"},
            "basis": [{"field": field, "evidence_ids": ["e0", "e1"], "source_ids": ["source_1"]}
                      for field in ("root_cause", "resolution")]}


def fixture_review():
    return {"checks": {name: {"verdict": "pass", "reason": "符合本次训练条件和证据"} for name in CHECKS},
            "claims": [{"field": field, "supported": True, "source_ids": ["source_1"],
                        "reason": "提供的摘录支持这一结论"} for field in ("root_cause", "resolution")]}


def decision(**changes):
    value = {"intent": "request_evidence", "evidence_ids": ["job_log"], "collection_guidance": False,
             "acknowledges_impact": False, "clear_next_step": False, "action_quote": "", "reply": "我查一下。"}
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


class TicketQualityTests(unittest.TestCase):
    def test_official_html_parser_prefers_article_over_navigation(self):
        parser = _PageText()
        parser.feed("<header>Sign in</header><nav>All services</nav><main><h1>Glue networking</h1>"
                    "<p>Private subnets use elastic network interfaces.</p><br/>"
                    "<p>Review routes and security groups.</p></main><footer>Feedback</footer>")
        text = " ".join(parser.main_parts)
        self.assertIn("Private subnets", text)
        self.assertIn("Review routes", text)
        self.assertNotIn("All services", text)
        self.assertNotIn("Feedback", text)

    def setUp(self):
        self.case = fixture_case()
        self.controls = copy.deepcopy(self.case["controls"])
        self.sources = [{"id": "source_1", "url": "https://docs.aws.amazon.com/glue/latest/dg/monitor-spark-ui-jobs.html",
                         "text": "Synthetic test fixture, not a real AWS claim.", "origin": "curated_fact"}]

    def test_controls_and_references_are_hard_gates(self):
        validate_case(self.case, self.controls, {"source_1"}, {"glue", "emr"})
        self.assertEqual(set(self.case["expected"]), {"background", "scenario", "problem",
            "investigation_steps", "reasoning", "root_cause", "resolution", "verification"})
        for change in ("impact", "cross_service", "unknown_evidence", "unknown_source", "duplicate", "answer_leak"):
            bad = copy.deepcopy(self.case)
            if change == "impact": bad["controls"]["impact"] = "production_down"
            elif change == "cross_service": bad["related_service_ids"] = ["emr"]
            elif change == "unknown_evidence": bad["basis"][0]["evidence_ids"] = ["made_up"]
            elif change == "unknown_source": bad["basis"][0]["source_ids"] = ["made_up"]
            elif change == "duplicate": bad["evidence"][1]["id"] = "e0"
            elif change == "answer_leak": bad["opening"] += bad["expected"]["root_cause"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_case(bad, self.controls, {"source_1"}, {"glue", "emr"})

    def test_seed_selection_cannot_ignore_controls(self):
        self.assertIsNone(choose_case("troubleshooting", set(), difficulty="advanced", cross_service=False))
        seed = choose_case("troubleshooting", set(), difficulty="basic", impact="development", cross_service=False)
        self.assertEqual(seed["id"], "glue-bookmark-commit")
        self.assertIsNone(choose_case("configuration", set(), difficulty="basic", impact="production_down"))

    def test_review_failure_repairs_once_then_freezes_with_source_mapping(self):
        rejected = fixture_review()
        rejected["checks"]["evidence_support"] = {"verdict": "fail", "reason": "目前的证据还不能排除替代解释"}
        with patch("app.services.ticket_quality.source_catalog", return_value=self.sources), \
             patch("app.services.ticket_quality.preferred_official_source",
                   return_value=(self.sources[0]["url"], "fixture excerpt")), \
             patch("app.services.ticket_quality.get_llm") as llm:
            llm.return_value.chat.side_effect = [json.dumps(self.case), json.dumps(rejected),
                                                json.dumps(self.case), json.dumps(fixture_review())]
            result = build_reviewed_case({"id": "glue"}, self.controls, {}, {"glue"}, "test")
        self.assertEqual(len(result["quality"]["attempts"]), 2)
        self.assertEqual(result["quality"]["status"], "ai_reviewed")
        self.assertEqual(result["source_records"], self.sources)
        self.assertEqual(len(result["quality"]["snapshot_sha256"]), 64)

    def test_repeated_quality_failure_never_creates_ready_case(self):
        rejected = fixture_review()
        rejected["checks"]["solvable"]["verdict"] = "fail"
        with patch("app.services.ticket_quality.source_catalog", return_value=self.sources), \
             patch("app.services.ticket_quality.get_llm") as llm:
            llm.return_value.chat.side_effect = [json.dumps(self.case), json.dumps(rejected)] * 2
            with self.assertRaisesRegex(ValueError, "未通过案例质量检查"):
                build_reviewed_case({"id": "glue"}, self.controls, {}, {"glue"}, "test")
            self.assertEqual(llm.return_value.chat.call_count, 4)

    def test_absent_sources_never_become_verified_even_if_reviewer_says_pass(self):
        for basis in self.case["basis"]: basis["source_ids"] = []
        review = fixture_review()
        for claim in review["claims"]: claim["source_ids"] = []
        with patch("app.services.ticket_quality.source_catalog", return_value=[]), \
             patch("app.services.ticket_quality.get_llm") as llm:
            llm.return_value.chat.side_effect = [json.dumps(self.case), json.dumps(review)]
            result = build_reviewed_case({"id": "glue"}, self.controls, {}, {"glue"}, "test")
        self.assertEqual(result["quality"]["status"], "needs_review")
        self.assertEqual(result["sources"], [])

    def test_document_fetch_rejects_untrusted_urls_without_network(self):
        with patch("app.services.ticket_quality.httpx.Client") as client:
            for url in ("http://127.0.0.1/private", "https://docs.aws.amazon.com.attacker.example/", "file:///etc/passwd"):
                self.assertEqual(fetch_official_excerpt(url), "")
            client.assert_not_called()

    def test_ticket_sources_only_use_curated_facts_and_captured_official_excerpt(self):
        document = KnowledgeDocument(document_id="doc:glue:network:0:chunk:001",
                                     title="Network", source_type="official_doc",
                                     content="已抓取的官方正文节选", service_id="glue",
                                     url="https://docs.amazonaws.cn/glue/latest/dg/start-connecting.html")
        with patch("app.services.ticket_quality.retrieve_resources",
                   return_value=[RetrievedDocument(document, 0.9, "test")]) as retrieve, \
             patch("app.services.ticket_quality.preferred_official_source") as fetch:
            records = source_catalog({"id": "glue", "name": "AWS Glue"}, query="网络")
            fetch.assert_not_called()
        self.assertEqual(retrieve.call_args.kwargs["source_types"], ["official_doc"])
        self.assertTrue(any(record["origin"] == "curated_fact" for record in records))
        self.assertTrue(any(record["text"] == "已抓取的官方正文节选" for record in records))

    def test_official_sources_prefer_china_chinese_then_global_chinese(self):
        english = "https://docs.aws.amazon.com/glue/latest/dg/programming-etl-connect-bookmarks.html"
        candidates = official_url_candidates(english)
        self.assertEqual(candidates[0], "https://docs.amazonaws.cn/glue/latest/dg/programming-etl-connect-bookmarks.html")
        self.assertEqual(candidates[1], "https://docs.aws.amazon.com/zh_cn/glue/latest/dg/programming-etl-connect-bookmarks.html")
        with patch("app.services.ticket_quality.fetch_official_excerpt",
                   side_effect=["", "这是一份官方中文文档，说明如何在作业初始化和提交时保存状态。"] ) as fetch:
            url, excerpt = preferred_official_source(english)
        self.assertEqual(url, candidates[1])
        self.assertIn("中文文档", excerpt)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], candidates[:2])

    def test_english_china_path_is_rewritten_and_english_body_is_rejected(self):
        english = "https://docs.amazonaws.cn/en_us/glue/latest/dg/start-connecting.html"
        candidates = official_url_candidates(english)
        self.assertEqual(candidates[0], "https://docs.amazonaws.cn/glue/latest/dg/start-connecting.html")
        self.assertEqual(candidates[1], "https://docs.aws.amazon.com/zh_cn/glue/latest/dg/start-connecting.html")
        self.assertNotIn("/en_us/", candidates[0])
        with patch("app.services.ticket_quality.fetch_official_excerpt", side_effect=[
            "Setting up network access to data stores for Glue jobs.",
            "设置对数据存储的网络访问。作业通过私有网络接口访问数据存储，并检查子网与路由配置。",
        ]) as fetch:
            url, excerpt = preferred_official_source(english)
        self.assertEqual(url, candidates[1])
        self.assertIn("设置对数据存储", excerpt)
        self.assertEqual(fetch.call_count, 2)


class CustomerStateTests(unittest.TestCase):
    def setUp(self):
        self.case = get_case("glue-public-api-nat")

    def turn(self, persona, question, response, state=None, supported=True):
        with patch("app.services.ticket_dialogue.get_llm") as llm:
            llm.return_value.chat.side_effect = [response, json.dumps({"supported": supported, "reason": "仅表达已有事实"})]
            result = run_customer_turn(self.case, PERSONAS[persona], "模拟客户", [], question, "test", state)
            # Neither generator nor guard may access the hidden answer.
            self.assertNotIn(self.case["expected"]["root_cause"], str(llm.return_value.chat.call_args_list))
            return result

    def test_same_request_differs_by_expertise_and_guidance_unlocks_novice(self):
        novice = self.turn("novice_pm", "请提供作业日志", decision())
        expert = self.turn("cloud_engineer", "请提供作业日志", decision())
        self.assertEqual(novice["evidence_ids"], [])
        self.assertEqual(novice["state"]["pending_evidence_ids"], ["job_log"])
        self.assertNotIn(self.case["evidence"][0]["content"], novice["reply"])
        self.assertEqual(expert["evidence_ids"], ["job_log"])
        guided = self.turn("novice_pm", "请打开 Glue 作业运行记录，点击这次失败的运行并复制错误日志。",
                           decision(intent="give_guidance", collection_guidance=True), novice["state"])
        self.assertEqual(guided["evidence_ids"], ["job_log"])
        self.assertEqual(guided["state"]["pending_evidence_ids"], [])

    def test_social_messages_and_unknown_ids_cannot_release_evidence(self):
        social = self.turn("cloud_engineer", "谢谢你的日志信息", decision(intent="social"))
        self.assertEqual(social["evidence_ids"], [])
        unknown = self.turn("cloud_engineer", "请给我那个文件", decision(evidence_ids=["invented"]))
        self.assertEqual(unknown["evidence_ids"], [])

    def test_repeat_uses_existing_facts_and_updates_emotion(self):
        first = self.turn("cloud_engineer", "请提供作业日志", decision())
        second = self.turn("cloud_engineer", "请提供作业日志", decision(), first["state"])
        self.assertEqual(second["state"]["known_evidence_ids"], ["job_log"])
        self.assertGreater(second["state"]["frustration"], first["state"]["frustration"])
        self.assertIn("之前提供过", second["reply"])

    def test_unfounded_reply_is_replaced_and_actions_are_not_marked_complete(self):
        unsafe = self.turn("cloud_engineer", "请提供作业日志", decision(reply="我修改配置后已经彻底恢复了。"), supported=False)
        self.assertTrue(unsafe["reply_guard_fallback"])
        self.assertNotIn("彻底恢复", unsafe["reply"])
        action = "请先修改训练环境配置"
        result = self.turn("cautious_ops", action, decision(intent="propose_change", action_quote=action))
        self.assertEqual(result["state"]["pending_actions"][0]["status"], "待执行确认")
        self.assertEqual(result["evidence_ids"], [])

    def test_complete_change_contract_is_acknowledged_without_repeating_question(self):
        first_question = "请在测试环境增加 job.commit()"
        first = self.turn("novice_pm", first_question,
                          decision(intent="propose_change", action_quote=first_question))
        second_question = ("操作范围限定为开发测试环境，只修改 job.commit()；风险异常时停止并恢复备份；"
                           "验证时连续运行两次并对比输入输出指标。")
        second = self.turn("novice_pm", second_question,
                           decision(intent="propose_change", action_quote=second_question), first["state"])
        self.assertIn("已经说明清楚", second["reply"])
        self.assertNotIn("请说明操作范围", second["reply"])
        self.assertEqual(len(second["state"]["pending_actions"]), 1)

    def test_report_rejects_fabricated_conversation_citation(self):
        from app.services.ticket_simulation import DIMENSIONS
        result = {"summary": "复盘摘要", "dimensions": {key: {"score": 3, "reason": "存在部分依据",
            "citations": [{"turn": 99, "role": "user", "quote": "这句话没有出现过"}], "next_step": "补充真实证据"} for key in DIMENSIONS}}
        with patch("app.services.ticket_simulation.get_llm") as llm:
            llm.return_value.chat.return_value = json.dumps(result)
            with self.assertRaisesRegex(ValueError, "真实对话不一致"):
                grade_ticket(self.case, [], "这是一段实际的结案方案", [], "test")

    def test_report_uses_weighted_scores_and_caps_critical_gap(self):
        from app.services.ticket_simulation import DIMENSIONS
        answer = "我会核对同一输入的耗时和分区指标，先在测试环境验证。"
        scores = {key: (1 if key == "technical_judgment" else 5) for key in DIMENSIONS}
        result = {"summary": "需要修正技术判断", "dimensions": {key: {
            "score": value, "reason": "引用最终回复作为评判依据",
            "citations": [{"turn": 0, "role": "final", "quote": answer}],
            "next_step": "说明证据与判断之间的关系"} for key, value in scores.items()}}
        with patch("app.services.ticket_simulation.get_llm") as llm:
            llm.return_value.chat.return_value = json.dumps(result, ensure_ascii=False)
            report = grade_ticket(self.case, [], answer, [], "test")
        self.assertEqual(report["overall_score"], 59)
        self.assertTrue(report["critical_gap"])
        self.assertEqual(sum(item["weight"] for item in report["dimensions"]), 100)

    def test_report_excludes_unobserved_dimension_without_penalty(self):
        from app.services.ticket_simulation import DIMENSIONS
        answer = "我会先确认指标基线，再给出测试环境的验证方法。"
        result = {"summary": "按可观察行为评分", "dimensions": {key: {
            "score": 0 if key == "evidence" else 4,
            "not_observed": key == "evidence", "reason": "本次未获得额外证据" if key == "evidence" else "依据最终回复",
            "citations": [] if key == "evidence" else [{"turn": 0, "role": "final", "quote": answer}],
            "next_step": "后续对比指标"} for key in DIMENSIONS}}
        with patch("app.services.ticket_simulation.get_llm") as llm:
            llm.return_value.chat.return_value = json.dumps(result, ensure_ascii=False)
            report = grade_ticket(self.case, [], answer, [], "test")
        self.assertEqual(report["overall_score"], 80)
        self.assertFalse(report["critical_gap"])
