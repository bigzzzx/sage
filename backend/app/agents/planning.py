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

from .common import (
    enforce_url_whitelist,
    filter_doc_pool_to_capabilities,
    load_learning_path,
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
2. **每天时长**：60 ~ 120 分钟
3. **每天 1 个 task**，围绕 1 个核心主题
4. **由浅入深**：
   - Day 1：概念入门（task_type = reading 或 review）
   - Day 2：进阶概念 + 配置规则（reading 或 review）
   - Day 3：动手实操初阶（lab）
   - Day 4：动手实操进阶 + 故障复现（lab 或 review）
   - Day 5：综合复盘 + 后测准备（quiz）
5. **每个 task 必须 cite 盲区**：targets_gap_ids 字段必须包含 1~2 个上面盲区的 gap_id
6. **覆盖度**：所有 severity=critical / major 的盲区都必须被至少一个 task 覆盖；minor 可酌情合并
7. **URL 白名单**：concepts[].url 必须严格来自上面"文档资料库"。资料库没有合适的，url 写空字符串 ""

# 每个 task 必填字段

- **objective**：一句话学完后能做到什么
- **targets_gap_ids**：cite 哪些盲区（gap_id 列表）
- **concepts**（数组，2~4 条）：核心概念点
  - 格式：{{"point": "30 字内一句话", "url": "<白名单 URL 或空字符串>"}}
- **hands_on**：Practical Exercise（动手实验）。**这是学习任务中最重要的部分**。
  必须像 AWS 内部培训的 Practical Exercise 一样：有明确步骤、有可观察的结果、有验证方式、有思考题。
  
  参考示例（L1 Crawler 入门的 Practical Exercise）：
  "1. 准备一个 CSV 文件上传到你的 S3 bucket（路径 s3://<your-bucket>/<your-folder>/sample.csv）
  2. 创建一个 Crawler，配置如下：
     - Data source: S3
     - S3 path: s3://<your-bucket>/<your-folder>/sample.csv
  3. 运行 Crawler
  4. 进入 Glue Console 查看生成的表，对比以下属性：
     - Table schema 是否与 CSV 列头一致
     - RecordCount（在 Advanced properties → Table properties → recordCount）
  5. 进入 Athena 执行 select * from <table_name>，确认数据可查
  6. 修改 Crawler 的 S3 path 指向另一个文件夹（含不同 schema 的数据）
  7. 再次运行 Crawler，观察 schema 变化，思考：为什么列变了？Crawler 的 schema 更新策略是什么？"

  hands_on 写作要求：
  - 编号步骤，每步一个动作
  - 步骤里要有具体的配置项名称、控制台路径、CLI 命令（不要泛泛说"打开控制台做实验"）
  - 必须有验证环节（"确认 XXX 是否符合预期"、"观察 YYY 变化"）
  - 最后一步留一个"思考题"引导学员深入理解（如"为什么…？"、"如果换成…会怎样？"）
  - 难度匹配 Day：Day 1~2 偏简单（创建资源、观察属性）；Day 3~4 偏复杂（故障复现、跨服务联调）
  - lab 类 task 至少 5~7 步；reading/review 类可以 3~4 步
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
- **time_minutes**: 60~120 整数

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
          "troubleshooting": "场景：...\\n排查练习：\\n1. ...\\n2. ...",
          "time_minutes": 90
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
) -> tuple[LearningPlan, AgentStep]:
    """生成学习计划，并返回 trace step。"""
    # 只展示与盲区相关的 capability 的文档池，减少噪声
    relevant_caps = sorted({g.capability_id for g in gaps}) if gaps else []
    if relevant_caps:
        pool_text, allowed_urls = filter_doc_pool_to_capabilities(svc, relevant_caps)
    else:
        # 全 service 文档池
        pool_text, allowed_urls = filter_doc_pool_to_capabilities(svc, [])

    # 加载 learning path
    lp_text = load_learning_path(svc.get("id", ""))
    learning_path_section = lp_text if lp_text else "（该服务暂无内部 Learning Path 数据）"

    prompt = _PLAN_PROMPT.format(
        service_name=service_name,
        overall_level=overall_level,
        capability_scores=json.dumps(capability_scores, ensure_ascii=False),
        gap_section=_format_gaps_for_prompt(gaps),
        learning_path_section=learning_path_section,
        doc_pool=pool_text,
    )

    valid_gap_ids = {g.gap_id for g in gaps}

    try:
        content, elapsed_ms = get_llm().chat_traced(
            [
                {"role": "system", "content": "你是 AWS 资深 SE 培训师，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
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
        )

    # ---------- 后端硬约束兜底 ----------
    weekly = data.get("weekly_plan", []) or []
    if weekly:
        weekly = [weekly[0]]
        weekly[0]["week"] = 1
        for t in weekly[0].get("tasks", []) or []:
            tm = int(t.get("time_minutes", 60) or 60)
            t["time_minutes"] = max(60, min(120, tm))
            # URL 白名单
            for c in t.get("concepts", []) or []:
                url = (c.get("url") or "").strip()
                if url and url not in allowed_urls:
                    c["url"] = ""
            # gap_ids 校验：保留真实存在的
            tg = t.get("targets_gap_ids", []) or []
            t["targets_gap_ids"] = [g for g in tg if isinstance(g, str) and g in valid_gap_ids]
        data["weekly_plan"] = weekly

    plan = LearningPlan(
        plan_name=data.get("plan_name", ""),
        overall_assessment=data.get("overall_assessment", ""),
        priority_dimensions=data.get("priority_dimensions", []),
        weekly_plan=[
            WeekPlan(
                week=w.get("week", 1),
                focus=w.get("focus", ""),
                tasks=[LearningTask(**t) for t in (w.get("tasks", []) or [])],
            )
            for w in (data.get("weekly_plan", []) or [])
        ],
        verification=data.get("verification", ""),
    )

    step = AgentStep(
        agent="planning",
        label="生成学习计划",
        input_summary=f"{len(gaps)} 个盲区，覆盖 {len(relevant_caps)} 个能力点",
        output_summary=f"{len(plan.weekly_plan[0].tasks) if plan.weekly_plan else 0} 个任务",
        elapsed_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return plan, step
