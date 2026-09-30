"""Grounded customer simulation and provisional ticket review.

The customer model never receives the hidden diagnosis/solution. Exact logs and
configuration facts are appended by the server from a vetted case bank.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from functools import lru_cache
from pathlib import Path

from app.agents.common import safe_json_loads
from app.services.llm import get_llm
from app.services.taxonomy import get_service, list_services

CASES_PATH = Path(__file__).resolve().parents[3] / "data" / "tickets" / "glue_cases.json"
CATEGORIES = {
    "troubleshooting": {"label": "故障排查与恢复", "description": "服务异常、连接失败、作业报错或不可用"},
    "configuration": {"label": "功能理解与配置指导", "description": "功能边界、配置方法与方案选型"},
    "performance": {"label": "性能与容量优化", "description": "延迟、吞吐、扩缩容与容量瓶颈"},
    "access_security": {"label": "权限与安全访问", "description": "AccessDenied、身份、资源策略与跨账号访问"},
    "data_integrity": {"label": "数据正确性与一致性", "description": "数据重复、遗漏、结果差异与同步延迟"},
    "migration_compat": {"label": "迁移、升级与兼容性", "description": "版本变化、迁移风险、兼容性与回滚"},
    "cost_quota": {"label": "成本、配额与资源使用", "description": "费用异常、限流、资源上限与使用优化"},
}
PERSONAS = {
    "novice_pm": {"label": "云服务新手产品经理", "names": ["林经理", "陈经理", "周经理"],
        "expertise": 1, "patience": 4, "cooperation": 4,
        "style": "懂业务目标但不熟悉 AWS 术语。若对方只说“提供日志”，先询问入口和需要哪一段；获得清晰指引后配合操作。"},
    "business_veteran": {"label": "熟悉业务的资深运营人员", "names": ["王经理", "刘经理", "赵经理"],
        "expertise": 2, "patience": 4, "cooperation": 4,
        "style": "非常了解业务流程和影响，AWS 知识有限。能准确说明业务现象，会追问技术方案对业务的影响。"},
    "junior_developer": {"label": "有基础的开发工程师", "names": ["小林", "小陈", "小周"],
        "expertise": 3, "patience": 4, "cooperation": 5,
        "style": "会部署、查看日志并执行操作，但可能误解配置或遗漏上下文。对明确的检查步骤配合度高。"},
    "cloud_engineer": {"label": "经验丰富的云工程师", "names": ["王工", "刘工", "赵工"],
        "expertise": 5, "patience": 3, "cooperation": 4,
        "style": "熟悉云服务和排障，已经做过基础检查。不接受无依据的重复建议，希望知道每一步检查的判断依据。"},
    "impatient_owner": {"label": "强势急躁的业务负责人", "names": ["李总", "孙总", "吴总"],
        "expertise": 1, "patience": 1, "cooperation": 2,
        "style": "关注损失、恢复时间和风险，语气强势且容易打断。只有在对方承认影响并给出明确下一步后才更愿意配合。"},
    "skeptical_engineer": {"label": "失去耐心的资深工程师", "names": ["郑工", "冯工", "蒋工"],
        "expertise": 5, "patience": 1, "cooperation": 2,
        "style": "有多次支持沟通经历，对重复提问很敏感。要求对方先利用已提供信息，再提出有新判断价值的问题。"},
    "cautious_ops": {"label": "谨慎的生产运维负责人", "names": ["何工", "高工", "罗工"],
        "expertise": 4, "patience": 4, "cooperation": 3,
        "style": "熟悉生产环境和变更流程。任何操作都追问影响范围、验证方法、维护窗口和回滚条件。"},
    "anchored_lead": {"label": "固执于既有判断的技术负责人", "names": ["唐工", "许工", "曹工"],
        "expertise": 4, "patience": 2, "cooperation": 2,
        "style": "经验丰富但已认定一个原因。除非对方用明确证据解释矛盾，否则会坚持自己的判断。"},
    # Compatibility for tickets created before the richer persona model.
    "new_user": {"label": "刚接触服务的客户", "names": ["林女士"], "expertise": 1,
        "patience": 4, "cooperation": 4, "style": "不熟悉 AWS 术语，需要明确操作指引。", "legacy": True},
    "engineer": {"label": "技术工程师", "names": ["王工"], "expertise": 3,
        "patience": 4, "cooperation": 4, "style": "熟悉基础术语，按问题提供配置和日志。", "legacy": True},
    "owner": {"label": "业务负责人", "names": ["李经理"], "expertise": 1,
        "patience": 2, "cooperation": 3, "style": "关注影响、恢复时间和风险。", "legacy": True},
}
DIMENSIONS = {
    "clarification": "需求与影响澄清",
    "evidence": "信息和证据处理",
    "technical_judgment": "技术判断",
    "resolution": "方案质量与风险控制",
    "communication": "客户沟通与预期管理",
    "verification": "验证、总结与交接",
}
SCORING_WEIGHTS = {
    "clarification": 15, "evidence": 20, "technical_judgment": 25,
    "resolution": 20, "communication": 10, "verification": 10,
}
SCORE_ANCHORS = {
    0: "有机会表现却未做，或捏造/误用关键信息",
    1: "仅泛泛提及，关键判断错误或不可执行",
    2: "相关方向正确，但没有说明具体证据或动作",
    3: "完成主要动作，证据、风险或后续步骤有明显缺口",
    4: "给出有依据、可执行的处理步骤并说明限制",
    5: "在 4 分基础上排除替代解释，处理风险与验证闭环完整",
}
DIMENSION_CRITERIA = {
    "clarification": "澄清现象、业务目标、范围、影响和优先级；客户已给出的信息不必重复索取",
    "evidence": "利用已提供或主动获取的日志、配置、指标；解释证据能证实/排除什么及其局限",
    "technical_judgment": "依据已展示证据判断根因或配置边界，区分已证实与待验证假设",
    "resolution": "给出可执行方案、影响范围、变更风险、回滚条件；不得把待执行操作写成已完成",
    "communication": "适配客户知识水平和情绪，说明下一步、预期时间和需要客户配合之处",
    "verification": "给出可检查的成功标准、复测步骤与交接信息；模拟环境没有执行入口时，完整可执行的验证计划可得满分，未执行本身不扣分，但不得宣称已验证成功",
}
CATEGORY_CRITERIA = {
    "troubleshooting": "优先确认影响、恢复路径、根因证据和回滚条件",
    "configuration": "优先确认需求、功能边界、配置选择和验证方法；不强求故障根因",
    "performance": "优先确认基线、瓶颈指标、容量和优化前后对比",
    "access_security": "优先确认身份、权限链、最小权限和变更风险",
    "data_integrity": "优先确认数据口径、重复/遗漏范围、证据及修复后的完整性",
    "migration_compat": "优先确认版本差异、兼容风险、分步迁移和回滚",
    "cost_quota": "优先确认费用或配额构成、取舍、预计收益及验证",
}
IMPACTS = {
    "development": "开发或测试环境受影响",
    "production_degraded": "生产环境部分功能受影响",
    "production_down": "核心生产业务中断",
}
DIFFICULTIES = {"basic": "基础", "intermediate": "进阶", "advanced": "高级"}
MAX_USER_TURNS = 12


@lru_cache(maxsize=1)
def load_cases() -> list[dict]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("工单场景库为空")
    ids = set()
    for case in cases:
        if (case.get("service_id") != "glue" or case.get("category") not in CATEGORIES
                or not case.get("opening") or not case.get("expected")
                or not case.get("evidence") or case.get("id") in ids):
            raise ValueError("工单场景库结构无效")
        ids.add(case["id"])
        evidence_ids = [item.get("id") for item in case["evidence"]]
        if len(evidence_ids) != len(set(evidence_ids)) or any(not item for item in evidence_ids):
            raise ValueError("工单证据 ID 无效")
    return cases


def get_case(case_id: str) -> dict:
    return next((case for case in load_cases() if case["id"] == case_id), None) or _missing_case()


def _missing_case() -> dict:
    raise ValueError("工单场景已不可用")


def choose_case(category: str, used_ids: set[str], *, service_id: str = "glue",
                difficulty: str = "intermediate", impact: str = "production_degraded",
                cross_service: bool = False) -> dict | None:
    candidates = [case for case in load_cases() if case["category"] == category
                  and case["service_id"] == service_id and case.get("difficulty") == difficulty
                  and impact in case.get("impacts", []) and case.get("cross_service") == cross_service]
    if not candidates:
        return None
    fresh = [case for case in candidates if case["id"] not in used_ids]
    return secrets.choice(fresh or candidates)


def customer_opening(case: dict, persona_id: str, customer_name: str,
                     impact: str = "production_degraded") -> str:
    return f"您好，我是{customer_name}。{case['opening']}"


def _official_refs(service: dict) -> list[str]:
    refs = []
    for capability in service.get("capabilities", []):
        for ref in capability.get("doc_refs", []):
            url = ref.get("url")
            if ref.get("kind") == "official" and isinstance(url, str):
                refs.append(url)
    return list(dict.fromkeys(refs))[:6]


def generate_case(service_id: str, category: str, difficulty: str,
                  cross_service: bool, model_id: str, impact: str = "production_degraded",
                  seed: dict | None = None) -> dict:
    """Generate once, validate, and persist an immutable simulated case snapshot."""
    service = get_service(service_id)
    if not service or category not in CATEGORIES or difficulty not in DIFFICULTIES or impact not in IMPACTS:
        raise ValueError("无法为所选配置生成工单")
    from app.services.ticket_quality import build_reviewed_case
    controls = {"service_id": service_id, "category": category, "difficulty": difficulty,
                "impact": impact, "cross_service": cross_service}
    case = build_reviewed_case(service, controls, CATEGORIES[category],
                               {item["id"] for item in list_services()}, model_id, seed)
    case["id"] = f"generated-{uuid.uuid4().hex[:16]}"
    return case


def _parse_object(raw: str) -> dict:
    result = safe_json_loads(raw, {})
    if not isinstance(result, dict):
        raise ValueError("模型回复格式无效，请重试")
    return result


def customer_turn(case: dict, persona_id: str, customer_name: str,
                  messages: list[dict], question: str, model_id: str,
                  state: dict | None = None) -> dict:
    from app.services.ticket_dialogue import run_customer_turn
    return run_customer_turn(case, PERSONAS[persona_id], customer_name,
                             messages, question, model_id, state)


def customer_reply(case: dict, persona_id: str, customer_name: str,
                   messages: list[dict], question: str, model_id: str,
                   difficulty: str = "intermediate") -> tuple[str, list[str]]:
    """Compatibility wrapper for scripts; the API persists the full turn state."""
    turn = customer_turn(case, persona_id, customer_name, messages, question, model_id)
    return turn["reply"], turn["evidence_ids"]


def _grade_ticket_once(case: dict, messages: list[dict], final_answer: str,
                       revealed_ids: list[str], model_id: str,
                       persona_id: str | None = None, state: dict | None = None) -> dict:
    """A bounded AI teaching assessment, explicitly not expert certification."""
    transcript, turn = [], 0
    for message in messages:
        if message["role"] == "user":
            turn += 1
        transcript.append({**message, "turn": turn})
    transcript.append({"role": "final", "turn": 0, "content": final_answer})
    prompt = {
        "case_truth": case["expected"],
        "official_sources": case["sources"],
        "revealed_evidence_ids": revealed_ids,
        "conversation": transcript,
        "final_answer": final_answer,
        "dimensions": DIMENSIONS,
        "scoring_rubric": {"anchors": SCORE_ANCHORS, "dimension_criteria": DIMENSION_CRITERIA,
                           "category_focus": CATEGORY_CRITERIA.get(case.get("category", ""), ""),
                           "weights": SCORING_WEIGHTS},
        "customer_persona": PERSONAS.get(persona_id or "", {}),
        "customer_state": state or {},
        "case_quality": case.get("quality", {}).get("status", "legacy_unreviewed"),
    }
    raw = get_llm().chat([
        {"role": "system", "content": (
            "你是技术支持教学评审。仅按给定工单真相、已展示证据和对话评分；"
            "不要把模拟情节说成真实 AWS 实操，不要把用户未做的步骤写成已完成。"
            "只输出 JSON：{\"summary\":\"...\",\"investigation_steps\":[\"...\"],"
            "\"strengths\":[\"...\"],\"improvements\":[\"...\"],"
            "\"dimensions\":{\"clarification\":{\"score\":0,\"reason\":\"...\",\"citations\":[{\"turn\":1,\"role\":\"user\",\"quote\":\"原文\"}],\"next_step\":\"...\"},"
            "\"evidence\":{\"score\":0,\"reason\":\"...\",\"citations\":[],\"next_step\":\"...\"},"
            "\"technical_judgment\":{\"score\":0,\"reason\":\"...\",\"citations\":[],\"next_step\":\"...\"},"
            "\"resolution\":{\"score\":0,\"reason\":\"...\",\"citations\":[],\"next_step\":\"...\"},"
            "\"communication\":{\"score\":0,\"reason\":\"...\",\"citations\":[],\"next_step\":\"...\"},"
            "\"verification\":{\"score\":0,\"reason\":\"...\",\"citations\":[],\"next_step\":\"...\"}}}。"
            "每项 score 为 0-5 整数；只根据对话中实际表现给分，说明具体依据。"
            "每个维度还必须提供 citations 数组，每项是 {turn:轮次整数,role:user/customer/final,"
            "quote:逐字原文摘录}，1-3 项，摘录 4-160 字；final 的 turn 必须是 0。"
            "得分大于 0 的维度必须有原文依据。每个维度还需 next_step 字段，写下一次具体怎么做或怎么问。"
            "模拟环境没有实际执行入口。验证维度评估计划的可执行性、成功标准、复测与交接；"
            "完整计划可以得 5 分，不因没有真实执行结果单独扣分。"
            "但必须区分建议、待执行和已验证，pending_actions 不是已经完成的操作，虚报执行或验证应扣分。"
            "客户情绪不是技术得分，不应因为客户不满意就否定正确的风险控制。"
            "对照 scoring_rubric 中的行为档位给分，说明为什么达到该档、距离下一档差什么。"
            "客户一开始给出的证据也算已提供证据，不要求用户重复索取；"
            "简短而正确的回答不因篇幅短扣分。引用必须至少有一条来自用户回复或最终总结，"
            "客户的话只能补充上下文。对尚无机会观察的维度设 not_observed=true、score=0，"
            "不能把未观察算作失败；其他维度设 not_observed=false。"
        )},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ], temperature=0, model=model_id)
    result = _parse_object(raw)
    scores = result.get("dimensions")
    if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS):
        raise ValueError("报告维度不完整，请重试")
    dimensions = []
    for key, label in DIMENSIONS.items():
        item = scores[key]
        if not isinstance(item, dict) or type(item.get("score")) is not int or not 0 <= item["score"] <= 5:
            raise ValueError("报告分数无效，请重试")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("报告评分依据缺失，请重试")
        citations = item.get("citations")
        if not isinstance(citations, list) or len(citations) > 3:
            raise ValueError("报告缺少对话引用，请重试")
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError("报告对话引用无效，请重试")
            quote = citation.get("quote")
            if (type(citation.get("turn")) is not int or not isinstance(quote, str)
                    or not 4 <= len(quote) <= 160 or not any(
                        row["turn"] == citation["turn"] and row["role"] == citation.get("role")
                        and quote in row["content"] for row in transcript)):
                raise ValueError("报告引用与真实对话不一致，请重试")
        if item["score"] > 0 and not citations:
            raise ValueError("报告得分没有对话依据，请重试")
        if item["score"] > 0 and not any(citation.get("role") in {"user", "final"}
                                          for citation in citations):
            raise ValueError("报告得分缺少学员行为依据，请重试")
        next_step = item.get("next_step")
        if not isinstance(next_step, str) or not next_step.strip():
            raise ValueError("报告缺少具体改进建议，请重试")
        not_observed = item.get("not_observed", False)
        if type(not_observed) is not bool or (not_observed and item["score"] != 0):
            raise ValueError("报告未观察维度标记无效，请重试")
        if not_observed and key in {"technical_judgment", "resolution"}:
            raise ValueError("技术判断与方案质量必须依据最终回复评分")
        score = item["score"]
        dimensions.append({"id": key, "label": label, "score": score,
                           "max_score": 5, "weight": SCORING_WEIGHTS[key],
                           "not_observed": not_observed, "reason": reason[:600], "citations": citations,
                           "next_step": next_step[:500]})
    def short_list(name: str) -> list[str]:
        value = result.get(name)
        if not isinstance(value, list):
            return []
        return [item[:300] for item in value[:8] if isinstance(item, str) and item.strip()]
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("报告摘要缺失，请重试")
    observed = [item for item in dimensions if not item["not_observed"]]
    total_weight = sum(item["weight"] for item in observed)
    raw_score = round(sum(item["score"] * item["weight"] / 5 for item in observed)
                      * 100 / total_weight) if total_weight else 0
    critical_gap = any(item["id"] in {"technical_judgment", "resolution"}
                       and not item["not_observed"] and item["score"] <= 1
                       for item in dimensions)
    overall_score = min(raw_score, 59) if critical_gap else raw_score
    return {
        "status": "ai_provisional",
        "summary": summary[:700],
        "problem": case["expected"]["problem"],
        "user_answer": final_answer,
        "reference": case["expected"],
        "investigation_steps": short_list("investigation_steps"),
        "strengths": short_list("strengths"),
        "improvements": short_list("improvements"),
        "dimensions": dimensions,
        "overall_score": overall_score,
        "scoring_version": "ticket_v3",
        "critical_gap": critical_gap,
        "sources": case["sources"],
        "case_quality": case.get("quality", {}),
        "source_records": case.get("source_records", []),
        "claim_basis": case.get("basis", []),
        "pending_actions": (state or {}).get("pending_actions", []),
        "note": "AI 教学反馈，仅依据模拟工单与对话；引用已核对原文，技术判断仍需人工抽查。"
                + (" 本案例的技术资料支持尚不完整。" if case.get("quality", {}).get("source_status") != "supported" else ""),
    }


def grade_ticket(case: dict, messages: list[dict], final_answer: str,
                 revealed_ids: list[str], model_id: str,
                 persona_id: str | None = None, state: dict | None = None) -> dict:
    """Retry one schema-invalid review while preserving every strict citation gate."""
    last_error: ValueError | None = None
    for _ in range(2):
        try:
            return _grade_ticket_once(case, messages, final_answer, revealed_ids,
                                      model_id, persona_id, state)
        except ValueError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error
