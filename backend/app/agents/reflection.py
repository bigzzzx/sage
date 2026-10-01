"""反思 Agent：检查学习计划是否真覆盖了所有重要盲区。

只做"评估和报告"，不会重新生成计划（避免演示当天抽风）。
输出 critique 文本，前端可以显示一个友好提示。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.schemas.assessment import AgentStep, KnowledgeGap, LearningPlan
from app.services.llm import get_llm

from .common import safe_json_loads


_REFL_PROMPT = """你是 AWS 培训质检专家。你的任务是审核一份"学习计划"是否真正覆盖了诊断出的知识盲区，以及计划质量是否达标。

# 知识盲区列表（来自诊断 Agent）
{gaps}

# 学习计划（来自规划 Agent）
{plan}

# 测评已给出的总体评级
{overall_level}

# 审核维度（逐条检查）

## 1. 盲区覆盖度
- 所有 severity=critical 的盲区是否都被至少一个 task 覆盖？（targets_gap_ids 里有它）
- 所有 severity=major 的盲区是否都被至少一个 task 覆盖？
- minor 可以不覆盖，但如果被覆盖了更好

## 2. 内容对齐度
对每个 task，检查：
- task 声称针对的 gap（targets_gap_ids），task 的 objective / concepts / hands_on 内容是否**真的在讲这个盲区**？
- 如果 task 说"针对 SG 自引用规则"但内容全在讲 NAT Gateway → 这就是"声称覆盖但实际跑偏"

## 3. 计划质量
- hands_on 是否具体可执行？（有编号步骤 + 具体配置项 + 验证环节 + 思考题）还是泛泛"做个实验"？
- 创建/修改云资源的任务是否写明 preconditions、verification_steps、risk_and_cleanup？未实测的预期结果是否被误写成已完成？
- troubleshooting 是否有具体场景 + 引导提问？还是空泛的"思考怎么排查"？
- 是否由浅入深？（Day 1~2 概念 → Day 3~4 实操 → Day 5 复盘）
- 时长是否合理？（每天不超过 90 分钟，且任务步骤能在标注时间内完成）

## 4. 补强建议
如果发现问题，给出具体可执行的改进建议：
- "建议 Day 3 补充 SG 自引用的实操验证步骤"
- "Day 2 的 hands_on 太抽象，应加入具体 CLI 命令"

# 输出格式（严格 JSON，无 markdown 代码块）

{{
  "coverage_score": 1~5,
  "alignment_score": 1~5,
  "quality_score": 1~5,
  "overall_score": 1~5,
  "uncovered_gap_ids": ["列出 critical/major 盲区中未被覆盖的 gap_id"],
  "weak_alignment_tasks": [
    {{"day": "Day 3", "issue": "声称针对 gap_xxx（SG 自引用）但内容讲了 NAT Gateway"}}
  ],
  "quality_issues": [
    {{"day": "Day 2", "issue": "hands_on 只写了'做实验'，缺少具体步骤和验证环节"}}
  ],
  "suggestions": [
    "建议 Day 3 补充 Security Group 自引用配置的实操步骤（创建 → 去掉 → 观察报错 → 恢复）",
    "Day 5 的自测题建议覆盖本周所有 critical 盲区"
  ],
  "summary": "50 字以内整体评价"
}}

# 评分标准

**coverage_score**（盲区覆盖度）：
- 5分：所有 critical + major 盲区都被覆盖
- 3分：critical 覆盖了但有 major 遗漏
- 1分：有 critical 盲区未被覆盖

**alignment_score**（内容对齐度）：
- 5分：所有 task 内容与声称的 gap 完全对齐
- 3分：1~2 个 task 有轻微偏差
- 1分：多个 task 严重跑偏

**quality_score**（计划质量）：
- 5分：hands_on 具体可执行 + troubleshooting 有场景有引导 + 由浅入深 + 时长合理
- 3分：基本可用但有 1~2 处不够具体
- 1分：多处泛泛而谈，不可执行

**overall_score**：三项的加权平均（覆盖度 40% + 对齐度 30% + 质量 30%），四舍五入取整

# 重要规则
- 严格诚实：宁可挑刺，不要客气
- 总体评级来自测评输入，不能批评其“无依据”；AWS 全球区和中国区的官方文档不能仅因域名不同就判无效，仍需核对相邻技术断言是否被页面支持。
- S3 VPC Endpoint 只适用于 S3，不可把它作为任意公网 API 的 NAT 替代方案；缺少真实环境或前后对照时，不得认证“实操已验证”。
- 如果全部满分，suggestions 可以写空数组 []
- summary 要一针见血，不要客套话"""


_FLEX_REVIEW_PROMPT = """你是独立的学习计划评审。只根据提供的数据审核，不推断未提供的事实。
测评已给出的总体评级：{overall_level}
知识缺口（含答题证据）：{gaps}
学习任务（含实际操作、时长与资料）：{plan}
用户预算：{study_days} 天，每天最多 {minutes_per_day} 分钟。
检查 critical 缺口是否覆盖、major 缺口是否覆盖或明确延期、任务是否对准盲区、
实操是否能执行和验证、时长是否合理、引用链接是否明确。
创建或修改资源的任务须检查 preconditions、verification_steps、risk_and_cleanup，且不能把计划中的预期结果写成已执行结果。
总体评级是输入事实，不要误报为缺证据；docs.aws.amazon.com 与 docs.amazonaws.cn 都可能是官方文档，不能仅凭域名不同判引用错误，须核查相邻断言。
S3 VPC Endpoint 不能代替 NAT 让 Glue 访问任意公网 API；没有真实前后对照的任务仍是待实测。
技术事实的真实性若缺少原文支持，应在 quality_issues 里提出核验需求。
输出纯 JSON 对象，必须包含 1-5 的 coverage_score、alignment_score、quality_score、
overall_score，数组 uncovered_gap_ids、weak_alignment_tasks、quality_issues、suggestions，
以及简短 summary。具体问题给出 Day 与原因；不要凭空写已审核通过。"""


def run_reflection(
    gaps: list[KnowledgeGap],
    plan: LearningPlan,
    model: str | None = None,
    study_days: int = 5,
    minutes_per_day: int = 90,
    overall_level: str | None = None,
) -> tuple[dict, AgentStep]:
    """返回 (critique_dict, trace_step)。"""
    if not plan.weekly_plan:
        return {}, AgentStep(
            agent="reflection",
            label="计划质检",
            input_summary="无计划",
            output_summary="跳过（无计划）",
            status="skipped",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    # 序列化简化版 plan 给 LLM
    tasks_brief = []
    for t in plan.weekly_plan[0].tasks:
        tasks_brief.append({
            "day": t.day,
            "topic": t.topic,
            "task_type": t.task_type,
            "targets_gap_ids": t.targets_gap_ids,
            "objective": t.objective,
            "concepts": t.concepts,
            "hands_on": t.hands_on,
            "preconditions": t.preconditions,
            "verification_steps": t.verification_steps,
            "risk_and_cleanup": t.risk_and_cleanup,
            "troubleshooting": t.troubleshooting,
            "deliverable": t.deliverable,
            "time_minutes": t.time_minutes,
        })
    plan_text = json.dumps(tasks_brief, ensure_ascii=False, indent=2)

    gaps_brief = [
        {
            "gap_id": g.gap_id,
            "title": g.title,
            "severity": g.severity,
            "capability_id": g.capability_id,
            "misunderstanding": g.misunderstanding,
            "correct_understanding": g.correct_understanding,
            "evidence_quote": g.evidence_quote,
            "suggested_doc_urls": g.suggested_doc_urls,
        }
        for g in gaps
    ]
    gaps_text = json.dumps(gaps_brief, ensure_ascii=False, indent=2)

    template = (_REFL_PROMPT if (study_days, minutes_per_day) == (5, 90)
                else _FLEX_REVIEW_PROMPT)
    prompt = template.format(gaps=gaps_text, plan=plan_text,
                             study_days=study_days, minutes_per_day=minutes_per_day,
                             overall_level=overall_level or "（未提供）")

    try:
        content, elapsed_ms = get_llm().chat_traced(
            [
                {"role": "system", "content": "你是严格的 AWS 培训质检员，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            model=model,
        )
        critique = safe_json_loads(content, {})
        if not isinstance(critique, dict):
            critique = {}
    except Exception as e:  # noqa: BLE001
        return {}, AgentStep(
            agent="reflection",
            label="计划质检",
            input_summary=f"{len(gaps)} 个盲区 / {len(tasks_brief)} 个任务",
            output_summary=f"失败：{e}",
            status="failed",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    score_keys = ("coverage_score", "alignment_score", "quality_score", "overall_score")
    list_keys = ("uncovered_gap_ids", "weak_alignment_tasks", "quality_issues", "suggestions")
    if (any(isinstance(critique.get(key), bool) or
            not isinstance(critique.get(key), (int, float)) or
            not 1 <= critique[key] <= 5 for key in score_keys)
            or any(not isinstance(critique.get(key), list) for key in list_keys)):
        return {}, AgentStep(
            agent="reflection", label="计划质检",
            input_summary=f"{len(gaps)} 个盲区 / {len(tasks_brief)} 个任务",
            output_summary="审查输出结构不完整，不能视为通过",
            status="failed", elapsed_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    score = critique.get("overall_score", "?")
    uncovered = len(critique.get("uncovered_gap_ids", []) or [])
    suggestions_count = len(critique.get("suggestions", []) or [])
    summary = critique.get("summary", "")
    return critique, AgentStep(
        agent="reflection",
        label="计划质检",
        input_summary=f"{len(gaps)} 个盲区 / {len(tasks_brief)} 个任务",
        output_summary=f"总评 {score}/5，未覆盖 {uncovered}，{suggestions_count} 条建议。{summary}",
        elapsed_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
