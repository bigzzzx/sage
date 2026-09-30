"""规划 Agent：基于诊断 agent 输出的盲区，从白名单文档池中挑文档，写 5 天学习计划。

每个 task 必须 cite 1~2 个 gap_id，强制"针对盲区"。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.schemas.assessment import (
    AgentStep,
    KnowledgeGap,
    LearningPlan,
    LearningTask,
    WeekPlan,
)
from app.services.llm import get_llm
from app.services.rag import (curated_fact_documents, format_curated_fact_context,
                              format_retrieval_context, load_knowledge_documents,
                              retrieve_resources)

from .common import (
    enforce_url_whitelist,
    safe_json_loads,
)


_PLAN_PROMPT = """你是 AWS {service_name} 的资深 SE 培训师。一位 SE 刚做完测评，你看过他的答题诊断，现在要为他设计一份**5 个工作日的学习计划**，每天直击具体盲区。

# 测评背景
- 服务：{service_name}
- 总体评级：{overall_level}
- 各能力点得分：{capability_scores}

# 已识别的知识盲区（来自诊断 Agent，按重要度排序）
{gap_section}

# 内部 Learning Path 参考（制定学习计划时参考此路径的学习内容和练习场景）
{learning_path_section}

# 文档资料库（白名单，只能从这里选 URL）
{doc_pool}

# 设计原则（硬性约束）

1. **总周期**：恰好 5 个工作日（Day 1 ~ Day 5），weekly_plan 数组长度必须 = 1
2. **每天 1 个 task**，围绕 1 个核心主题
3. **由浅入深**：
   - Day 1：概念入门（task_type = reading 或 review）
   - Day 2：进阶概念 + 配置规则（reading 或 review）
   - Day 3：动手实操初阶（lab）
   - Day 4：动手实操进阶 + 故障复现（lab 或 review）
   - Day 5：综合复盘 + 后测准备（quiz）
4. **每个 task 必须 cite 盲区**：targets_gap_ids 字段必须包含 1~2 个上面盲区的 gap_id
5. **覆盖度与取舍**：critical 盲区必须覆盖；每项任务最多聚焦 1~2 个盲区。若 5 天不足以完成全部 major 盲区，把未覆盖的 major gap_id 放入 deferred_gap_ids，并在 overall_assessment 说明为何延期；不要为了表面全覆盖把多个实验塞进同一天。
6. **URL 白名单**：concepts[].url 必须严格来自上面"文档资料库"。资料库没有合适的，url 写空字符串 ""
7. **每日预算**：time_minutes 必须为 1~90 分钟；每一天只安排一个可在该时长内完成的必做交付物。阅读、准备、执行、核对和清理都计入预算。跨天依赖的 AWS 资源若尚未预置，不得假定在本日可以新建并完成多次运行；改为阅读/设计任务或延期到另一天。
8. **事实边界**：针对任意公网 API，不能将 S3 VPC Endpoint 写成 NAT 公网出口的替代品；S3 Endpoint 只解决到 S3 的私网访问。若证据不足，明确写“待核验”。
9. **实操安全**：每项任务给出账号/权限/预置资源等前置条件、可观察的验收方式；创建或修改 AWS 资源时写明可能的费用、隔离环境、回滚和清理。无法在预算内完成真实变更时改为观察/推演，并标明未实测，不得声称已修复。

# 每个 task 必填字段

- **objective**：一句话学完后能做到什么
- **preconditions**：实际执行所需账号、IAM 权限、预置资源和环境；纯阅读写“无需 AWS 资源”。
- **verification_steps**：谁在何处执行什么检查、观察到什么才算通过；计划中的预期结果不得写成已执行结果。
- **risk_and_cleanup**：资源费用/变更风险、隔离环境、回滚和清理步骤；无资源变更写“无资源变更”。
- **targets_gap_ids**：cite 哪些盲区（gap_id 列表）
- **concepts**（数组，2~4 条）：核心概念点
  - 格式：{{"point": "30 字内一句话", "url": "<白名单 URL 或空字符串>"}}
- **hands_on**：Practical Exercise（动手实验）。**这是学习任务中最重要的部分**。
  必须像 AWS 内部培训的 Practical Exercise 一样：有明确步骤、有可观察的结果、有验证方式、有思考题。
  
  参考示例（L1 Crawler 入门，前提是隔离账号已有测试 S3 路径与 Crawler）：
  "1. 只读确认测试 Crawler 指向的 S3 路径和样例 CSV；记录当前 Catalog 表的 schema。
  2. 在授权的测试环境运行一次现有 Crawler，记录运行 ID 与完成状态。
  3. 在 Glue Console 对比运行前后表 schema 和分区；若失败，查看运行日志并标记待排查，不声称验证通过。
  4. 交付一张前后对比表；思考：修改 S3 数据格式后，Crawler 的 schema 更新策略会如何影响结果？"

  hands_on 写作要求：
  - 编号步骤，每步一个动作
  - 步骤里要有具体的配置项名称、控制台路径、CLI 命令（不要泛泛说"打开控制台做实验"）
  - 必须有验证环节（"确认 XXX 是否符合预期"、"观察 YYY 变化"）
  - 最后一步留一个"思考题"引导学员深入理解（如"为什么…？"、"如果换成…会怎样？"）
  - 难度匹配 Day：Day 1~2 优先只读观察和配置推演；Day 3~4 仅在预置隔离资源可用时做单一故障复现或联调，不在一天内叠加多个资源变更
  - lab 类 task 建议 3~5 个必做步骤，每步对应一种明确动作；额外探索列为选做，不纳入 time_minutes 或通过条件；reading/review 类可以 2~4 步
- **troubleshooting**：故障排查练习。**让学员模拟真实 SE 场景排查**。

  参考示例：
  "场景：客户报告 Glue Job 运行 30 分钟后超时失败，日志显示 'Connection timed out to RDS endpoint'。已知配置了 VPC Connection。
  
  排查练习：
  1. 你会首先检查哪 3 个方向？（提示：网络层 / 安全组 / 路由）
  2. 如果是 Security Group 问题，CloudWatch 日志中会有什么特征？
  3. 请写出完整排查清单（5 步以内），每步说明看什么、期望看到什么
  4. 如果最终定位到 SG 自引用缺失，修复前后有什么区别？为什么修复后就通了？"

  troubleshooting 写作要求：
  - 必须给一个具体场景（含错误信息或现象描述）
  - 用编号提问引导（不要直接给答案）
  - 问题要循序渐进：先"检查什么" → 再"如何判断" → 最后"如何解决 + 前后对比"
  - Day 1~2 的 troubleshooting 偏简单（1~2 个引导问题）；Day 3~4 偏深入（3~4 个引导问题）
  - Day 5（quiz）的 troubleshooting 可以是"综合回顾题"

- **deliverable**：本日学习的预期产出物（一句话说明"完成后你应该能交付什么"）。
  示例：
  - Day 1："画出 Glue Job 访问 S3/RDS 的网络拓扑草图，标注每条流量经过的网络组件"
  - Day 2："写一份 Glue Connection 配置 checklist（子网/SG/路由/DNS 四项）"
  - Day 3："截图证明 Test Connection 通过 + Athena 查询返回数据"
  - Day 4："完成一次故障复现：故意制造 SG 问题 → 观察报错 → 修复 → 截图"
  - Day 5："完成 SAGE 平台后测验证；整理本周学习笔记（盲区 → 理解 → 验证 三列表格）"

  deliverable 让学习计划"可检验"——学员知道自己做到什么程度算"学完了"。

- **task_type**: reading / review / lab / quiz

# 质量自检（输出前逐日检查）

- 同一天若同时要求创建 Connection、NAT Gateway、路由、Endpoint 和运行多个 Job，必须拆分或降级为拓扑推演；不能把这些都写成 90 分钟内必做。
- concepts[].url 只能引用确实支持该 point 的文档；白名单仅代表允许使用，不等于该页支持任意断言。不确定时将 url 留空、把断言写成待核验，并在 verification_steps 给出核验动作。
- 验证步骤必须覆盖成功与失败分支。例如 Job 成功但目标数据未变化、Job 失败或日志不足时各看什么；不能只写理想成功结果。
- 任何创建/修改/删除资源的任务都要写清具体隔离范围、所需权限、费用和回滚/清理；否则只安排只读观察。

# Day 5 quiz 的特殊要求

Day 5 是整周的综合复盘 + 后测准备，task_type 必须为 quiz。内容应包含：
1. **盲区回顾清单**：列出本周针对的所有盲区，每个写一句"现在我的理解是…"
2. **自测题**：针对本周重点给 2~3 道自测问题（可以是简答或判断对错）
3. **hands_on**：整理学习笔记的具体步骤（如"整理成 盲区 / 正确理解 / 验证方式 三列表格"）
4. **deliverable**：完成 SAGE 平台后测验证

# 输出格式（严格 JSON，无 markdown 代码块）

{{
  "plan_name": "针对 [关键盲区] 的 5 天强化学习计划",
  "overall_assessment": "结合盲区与得分，2~3 句点评 + 学习路径概述",
  "priority_dimensions": ["重点能力1", "重点能力2"],
  "deferred_gap_ids": ["时间预算内未覆盖的 major gap_id"],
  "weekly_plan": [
    {{
      "week": 1,
      "focus": "本周聚焦：xxx",
      "tasks": [
        {{
          "day": "Day 1",
          "topic": "主题",
          "task_type": "reading",
          "targets_gap_ids": ["gap_q3_0"],
          "objective": "...",
          "deliverable": "画出 Glue Job 网络拓扑草图，标注 ENI / SG / NAT 等组件",
          "concepts": [
            {{"point": "...", "url": "https://docs.amazonaws.cn/..."}},
            {{"point": "...", "url": ""}}
          ],
          "hands_on": "1. ...\\n2. ...\\n3. ...（含验证 + 思考题）",
          "preconditions": "需预置测试账号、Glue 角色与隔离 S3 路径；缺少时先做文档观察",
          "verification_steps": "运行后核对 Catalog 表元数据和 S3 原始对象；未运行则标待验证",
          "risk_and_cleanup": "仅在隔离环境创建资源；记录费用并在结束后删除测试资源",
          "troubleshooting": "场景：...\\n排查练习：\\n1. ...\\n2. ...",
          "time_minutes": 60
        }}
        ... (Day 2 ~ Day 5)
      ]
    }}
  ],
  "verification": "Day 5 完成后进入 SAGE 平台做后测验证"
}}

# 最后提醒
- weekly_plan 必须只有 1 周，tasks 必须正好 5 个
- 每个 task 的 targets_gap_ids 必须非空，且引用的 gap_id 必须真实存在于上面盲区列表
- URL 必须来自白名单
- 输出纯 JSON，不要任何前言后语"""


_FLEX_PLAN_PROMPT = """你是 AWS {service_name} 的资深 SE 培训师。根据测评证据生成可执行、有限预算的学习计划。只输出 JSON。

服务：{service_name}；总体评级：{overall_level}；能力分数：{capability_scores}
已识别知识缺口：{gap_section}
内部学习路径（仅作参考）：{learning_path_section}
允许引用的资料和事实：{doc_pool}

用户可投入 {study_days} 天，每天最多 {minutes_per_day} 分钟。
总体评级来自测评输入，不能把它当成模型猜测。针对任意公网 API，S3 VPC Endpoint 不是 NAT 公网出口的替代品；只在目标确为 S3 时讲 S3 Endpoint。
weekly_plan 恰好一周，tasks 恰好 {study_days} 项，day 顺序为 Day 1 至 Day {study_days}。
每项任务的 time_minutes 必须在 1 至 {minutes_per_day} 之间。先覆盖 critical，再覆盖 major；
时间不足时，未覆盖的 major gap_id 必须放进 deferred_gap_ids，并在 overall_assessment 说明延期原因。
critical 不得延期。不能把未覆盖缺口写成已经掌握。
每项任务的 targets_gap_ids 必须引用真实 gap_id，至少有一个；不许虚构 URL。
任务需包含 objective、deliverable、concepts（point/url）、hands_on、troubleshooting、task_type、time_minutes，
还需包含 preconditions（账号/权限/预置环境）、verification_steps（如何验收，不能冒充已实测）、risk_and_cleanup（费用/风险/回滚/清理；无资源变更时写明）。
hands_on 写出具体操作与可观察的验证结果；若 {minutes_per_day} 分钟内无法创建/修改所需资源，则改成观察或推演并标为待实测，不得承诺已修复。最后一日安排复盘与后测准备。

输出 JSON 对象，字段为 plan_name（字符串）、overall_assessment（字符串）、
priority_dimensions（字符串数组）、deferred_gap_ids（gap_id 字符串数组）、
weekly_plan（数组，恰好一个对象；对象含 week=1、focus、tasks）、verification（字符串）。
每个 tasks 项含 day、topic、task_type、targets_gap_ids、objective、deliverable、
concepts、hands_on、preconditions、verification_steps、risk_and_cleanup、troubleshooting、time_minutes。只输出纯 JSON。"""


def _as_text(value) -> str:
    """Keep useful model text when a provider returns an object for a text field."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "；".join(part for item in value.values()
                        if (part := _as_text(item)))
    if isinstance(value, list):
        return "；".join(part for item in value if (part := _as_text(item)))
    return str(value) if isinstance(value, (int, float)) else ""


def _format_gaps_for_prompt(gaps: list[KnowledgeGap]) -> str:
    if not gaps:
        return "（用户答得不错，未识别到明显盲区。请基于得分较低的能力点出 5 天巩固计划，targets_gap_ids 写空数组 []）"
    lines: list[str] = []
    for g in gaps:
        sev_marker = {"critical": "🔴", "major": "🟠", "minor": "🟡"}.get(g.severity, "⚪")
        urls = "\n    建议文档：" + "\n    ".join(g.suggested_doc_urls) if g.suggested_doc_urls else ""
        lines.append(
            f"- [{g.gap_id}] {sev_marker} {g.title}（capability: {g.capability_id}）\n"
            f"  错误理解：{g.misunderstanding}\n"
            f"  正确理解：{g.correct_understanding}{urls}"
        )
    return "\n".join(lines)


def run_planning(
    service_name: str,
    overall_level: str,
    capability_scores: dict[str, float],
    gaps: list[KnowledgeGap],
    svc: dict,
    model: str | None = None,
    review_feedback: str = "",
    study_days: int = 5,
    minutes_per_day: int = 90,
) -> tuple[LearningPlan, AgentStep, list[dict]]:
    """生成学习计划，并返回 trace step。"""
    # Only sources with verified text can be cited by a learning task. A
    # taxonomy URL without captured content is navigation, not evidence.
    relevant_caps = sorted({g.capability_id for g in gaps}) if gaps else []
    service_id = svc.get("id", "")
    trusted_docs = [doc for doc in load_knowledge_documents()
                    if doc.service_id == service_id and doc.source_type == "official_doc"
                    and (not relevant_caps or not doc.capability_id
                         or doc.capability_id in relevant_caps)]
    facts = curated_fact_documents(service_id)
    allowed_urls = {doc.url for doc in trusted_docs + facts if doc.url}
    pool_text = "\n".join(f"- [{doc.title}]({doc.url})"
                          for doc in {doc.url: doc for doc in trusted_docs + facts
                                      if doc.url}.values()) or "（暂无已核验正文的官方资料）"

    retrieval_query = "\n".join(
        f"{gap.title} {gap.misunderstanding} {gap.correct_understanding}" for gap in gaps
    ) or " ".join(relevant_caps)
    retrieved = retrieve_resources(
        query=retrieval_query, service_id=service_id,
        capability_ids=relevant_caps, limit=6,
    )
    paths = retrieve_resources(
        query=retrieval_query, service_id=service_id,
        limit=3, source_types=["learning_path"],
    )
    rag_context = format_retrieval_context(retrieved, query=retrieval_query)
    if facts:
        rag_context = ("# 已核验事实（优先）\n" + format_curated_fact_context(service_id)
                       + "\n# 其他检索结果\n" + rag_context)
    learning_path_section = (format_retrieval_context(paths, query=retrieval_query) if paths
                             else "（该服务暂无内部 Learning Path 数据）")

    template = (_PLAN_PROMPT if (study_days, minutes_per_day) == (5, 90)
                else _FLEX_PLAN_PROMPT)
    prompt = template.format(
        service_name=service_name,
        overall_level=overall_level,
        capability_scores=json.dumps(capability_scores, ensure_ascii=False),
        gap_section=_format_gaps_for_prompt(gaps),
        learning_path_section=learning_path_section,
        doc_pool=f"{pool_text}\n\n# RAG 检索资料（已核验事实优先；案例和学习路径不作事实依据）\n{rag_context}",
        study_days=study_days,
        minutes_per_day=minutes_per_day,
    )
    if review_feedback:
        prompt += ("\n\n# 上一版学习计划审查意见（仅修订一次）\n"
                   "请针对以下问题修订计划，并保持每个任务与所引用盲区的内容一致：\n"
                   f"{review_feedback[:1800]}")
    prompt += ("\n\n# 面向真实用户的可执行性约束\n"
               "单道选择题不能证明用户长期持有某种观点；用'本题选了'描述证据，"
               "短测不要称用户达到专家级或某领域完全掌握。"
               "每天优先给出一个能在预算内完成的必做任务，其余标为选做；"
               "创建 NAT、Glue Job 或改路由时要预留等待、费用与收尾时间。"
               "前一天要求删除的资源，下一天如需使用必须明确重建步骤。"
               "实验结果只写可能出现的分支与判读方法，不保证出现重复数据或一定成功。"
               "RAG 的 official_ref 只有链接元数据，不是事实证据；case 与 learning_path 也不能独立证明技术断言。"
               "每条关键技术断言附上文档池中直接相关且已抓到正文的官方 URL；没有对应来源则删去该断言。"
               "优先中文官方文档；资料池只有英文时可保留英文，并如实标注。"
               "避免外语混入中文说明，先给用户可理解的步骤，再给详细背景。")

    valid_gap_ids = {g.gap_id for g in gaps}

    try:
        content, elapsed_ms = get_llm().chat_traced(
            [
                {"role": "system", "content": "你是 AWS 资深 SE 培训师，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            model=model,
        )
        data = safe_json_loads(content, {})
        if not isinstance(data, dict):
            data = {}
    except Exception as e:  # noqa: BLE001
        return LearningPlan(plan_name="学习计划生成失败", overall_assessment=f"请重试（{e}）"), AgentStep(
            agent="planning",
            label="生成学习计划",
            input_summary=f"{len(gaps)} 个盲区",
            output_summary=f"失败：{e}",
            status="failed",
            error=str(e),
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ), []

    # ---------- 后端硬约束兜底 ----------
    weekly = data.get("weekly_plan", []) or []
    if isinstance(weekly, dict):
        weekly = [weekly]
    if not isinstance(weekly, list) or any(not isinstance(item, dict) for item in weekly):
        weekly = []
    if weekly:
        weekly = [weekly[0]]
        weekly[0]["week"] = 1
        tasks = weekly[0].get("tasks", []) or []
        if not isinstance(tasks, list):
            tasks = []
        weekly[0]["tasks"] = [item for item in tasks if isinstance(item, dict)]
        for t in weekly[0]["tasks"]:
            # URL 白名单
            concepts = t.get("concepts", []) or []
            if not isinstance(concepts, list):
                concepts = []
            t["concepts"] = [item for item in concepts if isinstance(item, dict)]
            for c in t["concepts"]:
                url = (c.get("url") or "").strip()
                if url and url not in allowed_urls:
                    c["url"] = ""
            # gap_ids 校验：保留真实存在的
            tg = t.get("targets_gap_ids", []) or []
            t["targets_gap_ids"] = [g for g in tg if isinstance(g, str) and g in valid_gap_ids]
        data["weekly_plan"] = weekly

    priority = data.get("priority_dimensions") or []
    if not isinstance(priority, list):
        priority = [priority]

    plan = LearningPlan(
        plan_name=_as_text(data.get("plan_name", "")),
        overall_assessment=_as_text(data.get("overall_assessment", "")),
        priority_dimensions=[_as_text(item) for item in priority
                             if _as_text(item)],
        deferred_gap_ids=[item for item in (data.get("deferred_gap_ids") or [])
                          if isinstance(item, str) and item in valid_gap_ids],
        weekly_plan=[
            WeekPlan(
                week=w.get("week", 1),
                focus=_as_text(w.get("focus", "")),
                tasks=[LearningTask(**t) for t in (w.get("tasks", []) or [])],
            )
            for w in (data.get("weekly_plan", []) or [])
        ],
        verification=_as_text(data.get("verification", "")),
    )

    step = AgentStep(
        agent="planning",
        label="生成学习计划",
        input_summary=f"{len(gaps)} 个盲区，检索 {len(retrieved)} 条资料",
        output_summary=f"{len(plan.weekly_plan[0].tasks) if plan.weekly_plan else 0} 个任务，检索方式：{retrieved[0].retrieval_method if retrieved else 'none'}",
        elapsed_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    sources = [
        {
            "document_id": item.document.document_id,
            "title": item.document.title,
            "source_type": item.document.source_type,
            "url": item.document.url,
            "excerpt": item.document.content[:300],
            "score": item.score,
            "capability_id": item.document.capability_id,
            "retrieval_method": item.retrieval_method,
        }
        for item in retrieved
    ]
    curated_sources = [{
        "document_id": doc.document_id, "title": doc.title,
        "source_type": doc.source_type, "url": doc.url,
        "excerpt": doc.content[:300], "score": 1.0,
        "capability_id": doc.capability_id, "retrieval_method": "curated",
    } for doc in facts]
    return plan, step, curated_sources + sources
