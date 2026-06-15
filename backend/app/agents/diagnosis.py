"""诊断 Agent：扮演资深 SE，对每道用户答得不好的题做"知识盲区分析"。

每题独立调用一次 LLM，输出结构化盲区列表（KnowledgeGap）。
学习计划只针对这些盲区出，不再凭"分数低"硬编。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.schemas.assessment import AgentStep, KnowledgeGap
from app.services.llm import get_llm

from .common import build_doc_pool, enforce_url_whitelist, safe_json_loads

# Checklist 加载（复用 question_gen 里的逻辑）
from pathlib import Path as _Path
import json as _json

_CHECKLIST_DIR = _Path(__file__).resolve().parents[3] / "data" / "taxonomy" / "checklist"


def _load_checklist_for_diagnosis(service_id: str) -> str:
    """加载该 service 的 checklist，供诊断 agent 参考定位用户盲区。"""
    lines: list[str] = []
    for f in sorted(_CHECKLIST_DIR.glob("*.json")):
        with open(f, encoding="utf-8") as fp:
            data = _json.load(fp)
        if data.get("service_id") != service_id:
            continue
        module = data.get("module", "")
        lines.append(f"## {module}")
        for q in data.get("questions", []):
            level = q.get("level", 100)
            qtype = q.get("type", "")
            question = q.get("question", "")
            level_str = f"L{level // 100}"
            lines.append(f"- [{level_str}][{qtype}] {question}")
        lines.append("")
    return "\n".join(lines).strip()


_DIAG_PROMPT = """你是 AWS {service_name} 的资深 SE 培训师，正在 review 一位 SE 的答题。
你的任务是像 senior SE 给后辈做技术 review 一样，**精准识别这名 SE 在这道题上暴露出的具体知识盲区**。

# 当前能力点（capability）
- ID：{capability_id}
- 名称：{capability_name}
- 描述：{capability_description}
- 评估等级参考：
  - L1：{level_l1}
  - L2：{level_l2}
  - L3：{level_l3}

# 该能力点对应的策展文档（白名单，挑选 suggested_doc_urls 只能从这里选）
{doc_pool}

# 该服务的内部培训考核要点（判断用户盲区时参考此清单精准定位缺失的知识点）
{checklist_section}

# 题目信息
- 题目类型：{question_type}
- 题目难度：{question_difficulty}
- 题目内容：{question}
- 评分要点（rubric）：{rubric}
- 参考答案：{reference_answer}
- 用户答案：{user_answer}
- 用户得分：{user_score}

# 诊断策略（按题目类型区分）

## 如果是选择题（type=choice）
选择题答错暴露的盲区通常是**概念混淆或记忆偏差**。
- 重点分析：用户为什么选了错误选项？是把 A 概念和 B 概念搞混了？还是对某个配置项的行为理解错了？
- 输出限制：**最多 1~2 条盲区**（一道选择题不可能暴露太多问题）
- severity 一般是 major（概念混淆）或 minor（记忆模糊），极少出现 critical

## 如果是开放题（type=open）
开放题答差暴露的是**更深层的能力缺口**：要点缺失、理解偏差、思路不系统。
- 重点分析：对比参考答案和 rubric，找出用户**具体哪些关键点**没说对、说错了、或完全没提到
- 输出限制：**最多 3~4 条盲区**
- severity 分布可以更广（critical / major / minor 都可能出现）

### L3 故障排查题的诊断参考（7 要素框架）
一个完整的故障排查回答应包含：
1. 系统化排查思路（从网络→权限→配置→代码，有优先级）
2. 具体检查手段（看什么日志/配置/指标，用什么工具）
3. 定位过程与证据（排除法：为什么不是 A、不是 B、锁定 C）
4. 根因解释（因果链：为什么这个原因导致这个现象）
5. 文档/知识副证（引用官方文档佐证结论）
6. 解决方案（具体改什么、怎么改、如何验证）
7. 前后对比（修改前为什么不行 → 修改后为什么行）

诊断时对照这 7 个要素，用户缺了哪个就是一个盲区。缺第 1~2 条 → 排查思路盲区；缺第 3~4 条 → 根因定位盲区；缺第 5 条 → 知识引用盲区；缺第 6~7 条 → 方案设计盲区。

# severity 判断标准（严格遵循）

| 级别 | 标准 | 例子 |
|---|---|---|
| **critical** | 方向性错误，会导致在客户场景下做出错误决策 | "认为 Glue Job 可以直接访问公网不需要 NAT"、"认为 Crawler 会转换数据" |
| **major** | 关键细节混淆或遗漏，方案落地会出问题 | "把 SG 自引用和 NACL 搞混"、"不知道 Crawler 的 schema 更新策略" |
| **minor** | 表述不精确或遗漏次要点，但理解方向正确 | "没提到 recordCount 属性"、"流程描述少了一步但主干对" |

**数量限制**：
- 选择题：critical 最多 1 条，major 最多 1 条，minor 不输出 → 总共最多 2 条
- 开放题：critical 最多 1 条，major 最多 2 条，minor 最多 1 条 → 总共最多 4 条

# 好诊断 vs 坏诊断（关键参考）

✅ 好诊断（具体到一个知识点）：
- title: "SG 自引用规则"
- misunderstanding: "用户认为配置 NACL 即可解决 Glue 内部通信问题"
- correct_understanding: "Glue 多个 ENI 之间通信依赖 Security Group 自引用规则，NACL 是无状态的无法满足"

❌ 坏诊断（泛泛而谈，禁止出现）：
- title: "网络知识不足"
- misunderstanding: "用户对网络理解不够深入"
- correct_understanding: "需要加强网络方面的学习"

❌ 坏诊断（过度解读，选择题不该出现）：
- 一道选择题输出 4 条盲区
- 从一个选择题推断出用户"不懂整个 VPC 体系"

# 输出要求

严格输出 JSON 数组（不要 markdown 代码块，不要其他说明）。
每个元素：
{{
  "title": "10 字内的盲区标题，如 'SG 自引用规则'",
  "misunderstanding": "用户具体的错误理解（30 字内，从用户答案推断）",
  "correct_understanding": "正确的理解应是什么（50 字内）",
  "evidence_quote": "从用户答案里截一句最能证明这个盲区的原话（30 字内）；如果用户根本没提，写 '未提及'",
  "severity": "critical | major | minor",
  "suggested_doc_urls": ["从上面文档池中挑 1~2 条最对症的 URL，必须一字不差；找不到合适的就给空数组 []"]
}}

# 重要规则
- 如果用户答案完全正确，输出空数组 []
- 选择题最多 2 条盲区，开放题最多 4 条
- 每条盲区必须**具体到一个知识点**，不允许泛泛评价
- evidence_quote 必须从用户答案里**原文截取**，不允许改写；用户没写相关内容就写"未提及"
- suggested_doc_urls 必须严格来自上面"该能力点对应的策展文档"中的 URL，不许编造"""


def _diagnose_one_question(
    service_name: str,
    capability: dict,
    question: dict,
    user_answer: str,
    user_score: float,
    doc_pool_text: str,
    allowed_urls: set[str],
    checklist_text: str = "",
) -> tuple[list[dict], int]:
    """诊断单题，返回 (gaps_raw, elapsed_ms)。"""
    levels = capability.get("levels", {}) or {}
    rubric = question.get("scoring_rubric") or []

    prompt = _DIAG_PROMPT.format(
        service_name=service_name,
        capability_id=capability.get("id", ""),
        capability_name=capability.get("name", ""),
        capability_description=capability.get("description", ""),
        level_l1=levels.get("L1", ""),
        level_l2=levels.get("L2", ""),
        level_l3=levels.get("L3", ""),
        doc_pool=doc_pool_text,
        checklist_section=checklist_text or "（该服务暂无内部考核清单）",
        question_type=question.get("type", "open"),
        question_difficulty=question.get("difficulty", "L2"),
        question=question.get("question", ""),
        rubric=json.dumps(rubric, ensure_ascii=False),
        reference_answer=question.get("reference_answer", "") or "（无）",
        user_answer=(user_answer or "").strip() or "（未作答）",
        user_score=user_score,
    )
    content, elapsed_ms = get_llm().chat_traced(
        [
            {"role": "system", "content": "你是 AWS 培训领域的资深 SE，输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    gaps = safe_json_loads(content, [])
    if not isinstance(gaps, list):
        gaps = []
    # 白名单兜底：每条 gap 的 suggested_doc_urls 只保留合法 URL
    for g in gaps:
        urls = g.get("suggested_doc_urls") or []
        g["suggested_doc_urls"] = [u for u in urls if isinstance(u, str) and u.strip() in allowed_urls]
    return gaps, elapsed_ms


def run_diagnosis(
    service_id: str,
    service_name: str,
    svc: dict,
    questions: list[dict],
    answers_map: dict[str, str],
    question_results: list[dict],
) -> tuple[list[KnowledgeGap], list[AgentStep]]:
    """对所有"答得不够好"的题做诊断。

    判断标准：
    - 选择题答错 → 诊断
    - 开放题平均得分 < 4.0（满分 5）→ 诊断
    - 其余跳过（节省 LLM 调用）
    """
    cap_by_id = {c.get("id"): c for c in svc.get("capabilities", []) or []}
    pool_text_full, allowed_full, by_cap = build_doc_pool(svc)

    # 加载该 service 的 checklist（一次加载，所有题共用）
    checklist_text = _load_checklist_for_diagnosis(service_id)

    gaps: list[KnowledgeGap] = []
    trace: list[AgentStep] = []

    # 把 question_results 按 id 索引
    qr_by_id = {r.get("question_id"): r for r in question_results}

    for q in questions:
        qid = q.get("id", "")
        cap_id = q.get("dimension_id", "")
        capability = cap_by_id.get(cap_id, {"id": cap_id, "name": cap_id})
        result = qr_by_id.get(qid, {})

        # 判断是否需要诊断
        qtype = q.get("type", "")
        if qtype == "choice":
            need = result.get("is_correct") is False
            score_5 = 0.0 if need else 5.0
        else:  # open
            score_5 = float(result.get("total_score", 0)) / 5.0  # total_score 是 25 分制
            need = score_5 < 4.0
        if not need:
            continue

        # 用 capability 自己的子文档池（缩短 prompt）
        cap_refs = by_cap.get(cap_id, [])
        cap_allowed = {r["url"].strip() for r in cap_refs if r.get("url")}
        cap_pool_lines = [f"- [{r.get('title','')}]({r.get('url','')}) — {r.get('summary','')}" for r in cap_refs if r.get("url")]
        cap_pool_text = "\n".join(cap_pool_lines) or "（该能力点暂无策展文档）"
        # 白名单仍以全 service 池为准（防止 LLM 偶尔引用其他能力点的文档）
        whitelist_for_question = allowed_full

        try:
            raw_gaps, elapsed_ms = _diagnose_one_question(
                service_name=service_name,
                capability=capability,
                question=q,
                user_answer=answers_map.get(qid, ""),
                user_score=score_5,
                doc_pool_text=cap_pool_text,
                allowed_urls=whitelist_for_question,
                checklist_text=checklist_text,
            )
        except Exception as e:  # noqa: BLE001
            trace.append(AgentStep(
                agent="diagnosis",
                label=f"诊断题目 {qid}",
                input_summary=f"capability={cap_id}, qtype={qtype}",
                output_summary=f"失败：{e}",
                status="failed",
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ))
            continue

        # 转换成 KnowledgeGap
        for idx, raw in enumerate(raw_gaps[:4]):
            gap_id = f"gap_{qid}_{idx}"
            gaps.append(KnowledgeGap(
                gap_id=gap_id,
                capability_id=cap_id,
                capability_name=capability.get("name", cap_id),
                question_id=qid,
                severity=str(raw.get("severity", "minor")).lower() or "minor",
                title=str(raw.get("title", ""))[:30],
                misunderstanding=str(raw.get("misunderstanding", ""))[:120],
                correct_understanding=str(raw.get("correct_understanding", ""))[:200],
                evidence_quote=str(raw.get("evidence_quote", ""))[:120],
                suggested_doc_urls=[u for u in (raw.get("suggested_doc_urls") or []) if isinstance(u, str)],
            ))

        trace.append(AgentStep(
            agent="diagnosis",
            label=f"诊断题目 {qid}",
            input_summary=f"capability={cap_id}, score={score_5:.1f}/5",
            output_summary=f"识别到 {len(raw_gaps)} 个盲区",
            elapsed_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))

    return gaps, trace
