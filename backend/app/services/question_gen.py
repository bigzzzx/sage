"""Generate assessments using service-scoped knowledge and a model."""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from app.services.llm import get_llm
from app.services.assessment_blueprint import FOCUS_LABELS, build_blueprint
from app.services.glue_sources import load_glue_facts
from app.services.assessment_fact_checks import false_g4x_explanation
from app.services.rag import (curated_fact_documents, format_curated_fact_context,
                              format_retrieval_context,
                              retrieve_resources)
from app.services.taxonomy import get_service

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CASES_DIR = DATA_DIR / "cases"


def _load_case_summaries(service_id: str, limit: int = 5) -> str:
    """加载该 service 的真实 case 摘要。"""
    lines = []
    for f in sorted(CASES_DIR.glob(f"{service_id}-*.json"))[:limit]:
        with open(f, encoding="utf-8") as fp:
            c = json.load(fp)
        lines.append(f"- [{c.get('difficulty','?')}] {c['title']}：{c.get('summary','')[:120]}")
    return "\n".join(lines)


CHECKLIST_DIR = DATA_DIR / "taxonomy" / "checklist"


def _load_checklist(service_id: str) -> str:
    """加载该 service 对应的 checklist 考点，格式化为 prompt 用的文本。"""
    lines: list[str] = []
    for f in sorted(CHECKLIST_DIR.glob("*.json")):
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        if data.get("service_id") != service_id:
            continue
        module = data.get("module", "")
        lines.append(f"## {module}")
        for q in data.get("questions", []):
            level = q.get("level", 100)
            qtype = q.get("type", "")
            question = q.get("question", "")
            # L100→L1, L200→L2, L300→L3
            level_str = f"L{level // 100}"
            lines.append(f"- [{level_str}][{qtype}] {question}")
        lines.append("")
    return "\n".join(lines).strip()


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s


PUBLIC_QUESTION_FIELDS = {"id", "type", "dimension_id", "difficulty", "question", "options", "multi_select"}

# High-confidence source-to-capability guards. Facts not listed here keep the
# existing flexible validation until their taxonomy mapping is reviewed.
GLUE_FACT_CAPABILITIES = {
    "crawler_catalog": {"glue_catalog"},
    "classifier_order": {"glue_catalog"},
    "g1x": {"glue_runtime", "glue_serverless_cost"},
    "g2x": {"glue_runtime", "glue_serverless_cost"},
    "g4x": {"glue_runtime", "glue_serverless_cost"},
    "partition_index": {"glue_catalog", "glue_data_lake"},
    "partition_projection": {"glue_catalog", "glue_data_lake"},
}


def mismatched_glue_fact_ids(question: dict) -> list[str]:
    return [source_id for source_id in question.get("source_ids", [])
            if source_id in GLUE_FACT_CAPABILITIES
            and question.get("dimension_id") not in GLUE_FACT_CAPABILITIES[source_id]]


def public_questions(questions: list[dict]) -> list[dict]:
    """Never send scoring keys, rubrics, or reference answers to a candidate."""
    return [{key: value for key, value in question.items() if key in PUBLIC_QUESTION_FIELDS}
            for question in questions]


def _validate_questions(questions: list[dict], allowed_caps: set[str],
                        allowed_fact_ids: set[str] | None = None,
                        blueprint: dict | None = None,
                        recent_stems: list[str] | None = None,
                        required_caps: set[str] | None = None) -> None:
    """Reject partial or malformed model output before it can become an assessment."""
    blueprint = blueprint or build_blueprint()
    count = blueprint["question_count"]
    if len(questions) != count or len({q.get("id") for q in questions}) != count:
        raise ValueError(f"出题数量或题目 ID 不符合 {count} 题要求")
    distribution = Counter((q.get("type"), q.get("difficulty")) for q in questions)
    if distribution != blueprint["expected"]:
        raise ValueError("题目类型或难度分布不符合本次测评配置")
    if required_caps and not required_caps.issubset({q.get("dimension_id") for q in questions}):
        raise ValueError("题目未覆盖所选能力点")
    stems = [_normalise_stem(str(q.get("question", ""))) for q in questions]
    previous = [_normalise_stem(stem) for stem in (recent_stems or [])]
    if any(not stem for stem in stems):
        raise ValueError("题目缺少题干")
    if recent_stems is not None and any(_near_duplicate(stem, other) for i, stem in enumerate(stems)
                                        for other in stems[:i] + previous):
        raise ValueError("本次题目与近期题目重复，请重新生成")
    for question in questions:
        if question.get("dimension_id") not in allowed_caps or not str(question.get("question", "")).strip():
            raise ValueError("题目缺少有效能力点或题干")
        if allowed_fact_ids is not None:
            source_ids = question.get("source_ids")
            if (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 3
                    or any(not isinstance(source_id, str) or source_id not in allowed_fact_ids
                           for source_id in source_ids)
                    or len(set(source_ids)) != len(source_ids)):
                raise ValueError("题目缺少有效的官方事实来源 ID")
            mismatches = mismatched_glue_fact_ids(question)
            if mismatches:
                raise ValueError(f"题目 {question.get('id')} 的考点 {', '.join(mismatches)} 与能力点不匹配")
        if question["type"] == "choice":
            options = question.get("options")
            answer = str(question.get("correct_answer", "")).strip().upper()
            if (not isinstance(options, list) or len(options) != 4
                    or any(not isinstance(option, str) or not option.strip() for option in options)
                    or len(set(options)) != 4 or len(answer) != 1 or answer not in "ABCD"
                    or question.get("multi_select") is True):
                raise ValueError("选择题选项或标准答案无效")
            question["correct_answer"] = answer
            if false_g4x_explanation(question):
                raise ValueError("题目解释把真实存在的 G.4X worker 误写为非 Glue 规格")
        elif (not isinstance(question.get("scoring_rubric"), list)
              or len(question["scoring_rubric"]) < 3
              or not str(question.get("reference_answer", "")).strip()):
            raise ValueError("开放题缺少评分要点或参考答案")


def _normalise_stem(stem: str) -> str:
    return re.sub(r"[\W_]+", "", stem.casefold())


def _near_duplicate(left: str, right: str) -> bool:
    return bool(left and right and (left == right or
                min(len(left), len(right)) >= 16 and SequenceMatcher(None, left, right).ratio() >= 0.9))


def _recent_question_stems(user_id: str, service_id: str, limit: int = 3) -> list[str]:
    from app.db import SessionLocal
    from app.models import QuestionSession

    with SessionLocal() as db:
        sessions = (db.query(QuestionSession).filter_by(user_id=user_id, service_id=service_id)
                    .order_by(QuestionSession.created_at.desc()).limit(limit).all())
        return [q.get("question", "") for session in sessions for q in (session.questions or [])]


def get_session(session_id: str, user_id: str) -> dict | None:
    from app.db import SessionLocal
    from app.models import QuestionSession

    with SessionLocal() as db:
        session = db.get(QuestionSession, session_id)
        if not session or session.user_id != user_id:
            return None
        from app.services.profile_scope import record_profile_id
        return {"service_id": session.service_id, "user_id": session.user_id,
                "profile_id": record_profile_id(session),
                "model_id": session.model_id,
                "study_days": session.study_days or 5,
                "minutes_per_day": session.minutes_per_day or 90,
                "kind": session.kind, "prev_assessment_id": session.prev_assessment_id,
                "questions": session.questions, "blueprint": session.blueprint}


def generate_questions(
    service_id: str,
    capability_ids: list[str] | None = None,
    question_count: int = 9,
    difficulty_profile: str = "balanced",
    focus: str = "comprehensive",
    post_test_gap_hints: list[str] | None = None,
    user_id: str = "",
    kind: str = "pre",
    prev_assessment_id: str | None = None,
    model_id: str | None = None,
    study_days: int = 5,
    minutes_per_day: int = 90,
    session_id: str | None = None,
    profile_id: str | None = None,
) -> tuple[str, list[dict]]:
    """基于可验证的测评蓝图生成并保存题目。返回 (session_id, questions_list)。"""
    blueprint = build_blueprint(question_count, difficulty_profile, focus)
    from app.services.profile_scope import service_in_profile, service_profile_id
    profile_id = profile_id or service_profile_id(service_id)
    if not service_in_profile(service_id, profile_id):
        raise ValueError("测评服务不属于指定 Profile")
    if session_id:
        existing = get_session(session_id, user_id)
        if existing:
            if (existing["profile_id"] != profile_id or existing["service_id"] != service_id or existing["kind"] != kind or
                    existing["prev_assessment_id"] != prev_assessment_id or
                    existing["model_id"] != model_id or
                    existing["study_days"] != study_days or
                    existing["minutes_per_day"] != minutes_per_day or
                    (existing["blueprint"] is not None and
                     any(existing["blueprint"].get(key) != blueprint[key]
                         for key in ("question_count", "difficulty_profile", "focus")))):
                raise ValueError("题目会话与原出题任务参数不一致")
            return session_id, existing["questions"]
    svc = get_service(service_id)
    if not svc:
        raise ValueError(f"Unknown service: {service_id}")

    all_caps = svc.get("capabilities", [])
    if capability_ids:
        if kind == "pre" and len(capability_ids) > 3:
            raise ValueError("专项测评最多选择 3 个能力点")
        selected_caps = [c for c in all_caps if c["id"] in capability_ids or c["name"] in capability_ids]
        if len(selected_caps) != len(set(capability_ids)):
            raise ValueError("所选能力点不属于当前服务")
    else:
        selected_caps = all_caps

    if not selected_caps:
        raise ValueError("该服务暂无可测评能力点")

    # 前测避免刷到近期原题；后测刻意复测盲区，不应被前测题干拦截。
    recent_stems = _recent_question_stems(user_id, service_id) if kind == "pre" and user_id else None
    choice_quota = blueprint["expected"]
    quota_text = "\n".join(
        f"- {kind} {level}: {choice_quota.get((kind, level), 0)} 道"
        for kind in ("choice", "open") for level in ("L1", "L2", "L3")
    )
    recent_section = ("\n# 近期题目（只用于避重，不得复制题干或同义改写）\n" +
                      "\n".join(f"- {stem[:180]}" for stem in recent_stems[:20])) if recent_stems else ""
    coverage_rule = ("所选每个能力点至少出 1 道题。" if capability_ids and kind == "pre" else
                     "尽量覆盖不同能力点；短测无法保证覆盖全部能力点，不要声称已全面评估。")

    cap_context = "\n".join(
        f"【{c['name']}】（id={c['id']}）{c['description']}"
        + f"\n  L1: {c['levels']['L1']}"
        + f"\n  L2: {c['levels']['L2']}"
        + f"\n  L3: {c['levels']['L3']}"
        for c in selected_caps
    )

    retrieval_query = " ".join(
        f"{cap['name']} {cap['description']}" for cap in selected_caps
    )
    retrieved = retrieve_resources(
        query=retrieval_query,
        service_id=service_id,
        capability_ids=[cap["id"] for cap in selected_caps],
        limit=5,
        source_types=["official_doc", "official_ref", "case", "learning_path"],
    )
    retrieved_context = format_retrieval_context(retrieved, query=retrieval_query)
    if service_id == "glue":
        case_section = (
            "\n# 已核验的公开 AWS Glue 考点（优先且仅据此陈述可核验的技术事实）\n"
            f"{format_curated_fact_context(service_id)}\n"
            "# 同一 RAG 知识库检索的补充素材（案例不可作事实依据；仅有链接的资料也不能作事实依据）\n"
            f"{retrieved_context}\n"
            "开放题可构造场景，但参考答案不得把未证实的内部实现、IAM action、唯一根因写成事实。"
            "若现象不足以定位唯一根因，应给出假设、验证步骤和条件化修复方案。\n"
        )
    else:
        case_section = (
            "\n# RAG 检索素材（案例与学习路径用于设计题目；只有官方正文能支持技术事实，不要照抄）\n"
            f"{retrieved_context}\n"
        )

    # 加载 checklist 考点池
    checklist_text = _load_checklist(service_id) if service_id != "glue" else ""
    checklist_section = f"""
# 考点范围（来自内部 Knowledge Check List，按题量抽样）

以下是该服务内部培训的考核要点，按 L1/L2/L3 分级。仅选取与本次能力点、题量和难度配额相符的考点，不要声称全部覆盖。出题时请确保：
- L1 题考 [L1] 标注的知识点
- L2 题考 [L2] 标注的知识点
- L3 题考 [L3] 标注的知识点
- 不要出超出以下范围的题目

{checklist_text}
""" if checklist_text else ""
    source_rule = ("每一道 Glue 题都必须有 source_ids 数组，引用上方已核验考点的 1~3 个 ID。"
                   "题目、解释、参考答案只可陈述这些来源明确支持的技术事实；"
                   "不要为凑题数引用不相关 ID。Worker 规格题归运行时或成本能力点，分区索引/投影题归数据目录或数据湖能力点，不得归作业可观测性。"
                   "所选能力点若没有适合的公开考点，不要硬凑题，直接输出空题目数组。source_ids 是供交卷后审查的证据索引。"
                   if service_id == "glue" else "")
    source_example = load_glue_facts()[0]["id"] if service_id == "glue" else "optional"

    # 后测盲区注入
    gap_section = ""
    if post_test_gap_hints:
        gap_lines = "\n".join(post_test_gap_hints)
        if service_id == "glue":
            gap_section = f"""
# 后测盲区提示（不是事实来源）

这些提示来自先前测评，其中可能包含未经核验的内部术语或错误标准答案。仅当盲区可由下方公开考点支持时，才据此设计后测题；否则忽略具体细节，改测相近的可核验能力点。不得把盲区文字直接当成标准答案或强制复述。

{gap_lines}
"""
        else:
            gap_section = f"""
# ⚠️ 后测验证重点（本次是后测，必须针对以下盲区出题）

以下是该用户在前测中暴露出的具体知识盲区。本次后测的核心目标是**验证用户是否已经掌握了这些盲区内容**。
出题时必须确保每个 critical/major 盲区都至少被 1 道题覆盖。题目应直击盲区本身，而不是泛泛地考该 capability。

{gap_lines}

出题策略：
- 选择题应考察盲区涉及的具体概念、配置项或行为机制
- 开放题应围绕盲区设计场景，验证用户能否正确解释/排查/解决
- 如果盲区提到"用户把 A 和 B 搞混了"，那就出一道区分 A 和 B 的题
"""

    prompt = f"""你是 AWS {svc['name']} 培训专家。请生成一套测评题目。

# 题目数量与难度（固定，不可更改）
- 选择题 {blueprint['num_choice']} 道，开放题 {blueprint['num_open']} 道，共 {question_count} 道
{quota_text}
- 每道题必须设置 dimension_id（从下方能力点 id 中选取）和 difficulty（L1/L2/L3）
- {coverage_rule}
- 出题侧重点：{FOCUS_LABELS[focus]}。仅作为内容偏好，不能牺牲服务事实依据、题型规则和难度配额。
{recent_section}

# 出题原则（非常重要）

## 选择题原则
选择题用于考察【知识点、概念、配置、API 行为、最佳实践、参数定义、组件作用】。

**强制规则（违反则视为不合格题目）：**
1. 题干长度不超过 2 句话，不能描述客户场景或日志报错
2. 题干**禁止**出现以下问法：
   - "以下哪个最可能是根本原因？"
   - "以下哪个最可能导致……？"
   - "以下哪种情况会引起……？"
   - "以下哪种排查方式最有效？"
   这些都是排查思路类问题，必须留给开放题
3. 题干**允许**的问法：
   - "X 的默认值/规格/限制是什么？"
   - "X 与 Y 的核心区别是什么？"
   - "为了实现 X，需要配置什么？"
   - "X 的作用/工作原理是什么？"
   - "在以下场景下，最佳实践是哪种？"（场景必须是设计选型，而非问题诊断）

**参考示例（单选题风格）：**

### 单选题风格特征
- 问的是"一个确定的事实/定义/行为"，答案唯一
- 题干问法："What is X?"、"What is the output of X?"、"Why did X happen?"
- 干扰项是其他组件/概念的描述，和正确答案属于同一维度但不同对象

示例 S1（L1 单选 - 组件定义）：
  题干：What is Glue crawler?
  选项：
  - A component of Glue that is responsible for crawling a data store and populating the Glue Data Catalog.（正确）
  - A component of Glue that is an index to the location, schema, and runtime metrics of your data.
  - A component of Glue that reads your source data, processes it, and then writes it out to your data target as output files.
  分析：三个选项分别描述 Crawler / Data Catalog / Job，只有一个对

示例 S2（L1 单选 - 输出物）：
  题干：What is the output of Crawler?
  选项：
  - Transformed data records that has been processed by the crawler.
  - Metadata of the data source (i.e. Glue datacatalog tables, partitions)（正确）
  - JSON-formatted files in S3 that retain the metadata of the data source.
  分析：考"Crawler 产出什么"，只有一个正确答案

示例 S3（L2 单选 - 配置差异）：
  题干：Athena partition projection 如何确定查询所需分区？
  选项：
  - 根据表属性推算分区值与位置。（正确）
  - 必须先由 crawler 枚举全部分区。
  - 读取 Spark executor 缓存。
  - 从 IAM policy 解析路径。
  分析：题干和正确答案均可通过官方文档核验

示例 S4（L3 单选 - 网络机制）：
  题干：Glue Job 在 VPC 中需要访问公网 API，为什么仅把子网设为公有子网仍不够？
  选项：
  - Glue ENI 没有公有 IP，通常需要 NAT 出口。（正确）
  - 必须先关闭 job bookmark。
  - 必须把 worker 改成 G.2X。
  - 必须启用 Athena partition projection。
  分析：考有官方文档支持的网络机制与配置

**从以上示例中总结出的选择题设计模式（必须遵循）：**
- **当前只出单选题**（multi_select 全部设为 false，correct_answer 只写一个字母）
- 单选题的核心：**问的是一个唯一事实**，干扰项来自同维度不同对象的真实描述
- L1 单选围绕"是什么 / 产出什么 / 某个具体事实"
- L2 单选围绕"某个配置的正确做法 / 两种方式的核心区别 / 某个行为的唯一原因"
- L3 单选围绕可核验的复杂配置差异、机制或边界；不要把未经核验的内部架构和唯一根因写成标准答案
- 干扰项用**容易混淆的相近概念**（如把 Crawler 的功能和 Job 的功能混、把 Data Catalog 和 Crawler 搞反），不是随便编
- 选项可以涉及具体的 API 名、方法名、参数名（如 extract_jdbc_conf()、from_catalog()），这是 L2 级别的正常深度

选项设计：
- 选项之间应是平行关系（不要长短不一、详略悬殊）
- 选项内容控制在一行能展示完
- 干扰项要看起来合理，但与正确答案有明确技术差异
- 避免编造不存在的参数/配置项
- 避免编造不存在的参数/配置项

## 开放题原则
开放题用于考察【诊断思路、根因分析、方案设计、综合判断能力】。

**三个难度级别的开放题定义（严格遵循）：**

### L1 开放题：基本概念问题
- 考察对服务核心组件、概念、基础架构的理解
- 不需要排查故障，不需要提供步骤
- 回答要求：解释清楚"是什么"和"为什么"
- 示例：
  - "EMR 集群中 Core 节点与 Task 节点有什么区别？"
  - "Glue Job 如何访问互联网？"
  - "Data Catalog 可以使用哪些 AWS 服务进行访问？"
  - "什么是 DAG？Spark 执行流程是什么？"
  - "Glue Job 的网络出口是什么？"
  - "Data locations 与 Data lake locations 分类是什么？"

### L2 开放题：流程/架构/简单排查
- 考察服务内部执行流程、组件交互方式、配置差异
- 可以包含简单的故障场景，但重点在"理解机制"而非"排查定位"
- 回答要求：描述流程/架构/差异，能说清楚"怎么工作的"
- 示例：
  - "Crawler 如何识别数据源并更新 Data Catalog 表元数据？"
  - "Dynamic Frame 与 Data Frame 的区别？"
  - "Spark 的提交流程（submit → driver → executor）"
  - "Crawler 自定义 classifier 与内置 classifier 的尝试顺序是什么？"
  - "Glue Job 通过 VPC endpoint 访问 S3 与通过 NAT 访问公网 API 有什么区别？"
  - "partition index 与 athena projection 的区别？加载分区的方式"
  - "Apply Mapping 有多少个 action，分别是什么？"
  - "启用 bookmark 后，job 的 concurrency 能否设置为 2，为什么？"

### L3 开放题：故障排查（核心）
- **必须提供一个具体的故障场景**：包括错误信息/现象/操作背景
- 要求回答者提供：排查思路 → 问题定位 → 根因分析 → 解决方案
- L3 开放题的回答必须能讲清楚：
  1. 问题原因是什么
  2. 解决前是什么状态、为什么不行
  3. 用什么方法解决
  4. 解决后是什么状态、为什么可以
- 示例：
  - "Spark 写 Hive 因临时文件过多从而影响写入速度，如何解决？（需讲清问题原因，解决前后的主要区别）"
  - "客户 Glue Job 报 Connection Timeout，连接 RDS 数据源失败。已知配置了 VPC Connection。请给出排查步骤和可能的根因。"
  - "Glue Crawler 运行后 Athena 查询报 HIVE_METASTORE_ERROR，表 schema 和实际数据不一致。分析可能原因并给出修复方案。"

**开放题 rubric 设计规则：**
- L1：给出 3 个评分要点（覆盖核心概念即可）
- L2：给出 4 个评分要点（覆盖流程完整性 + 关键细节）
- L3：给出 5 个评分要点（必须包含：根因定位、排查步骤合理性、解决方案可行性、前后对比清晰度、深度理解）

**开放题格式要求：**
- 题干结构：场景/背景（L3 必须有错误信息） + 问题
- reference_answer 必须详细（L3 至少 150 字），覆盖所有 rubric 要点

# 服务范围
本套题专门考察 AWS {svc['name']} 的能力。{svc.get('description', '')}

# 能力点定义（请严格围绕这些能力点出题）
{cap_context}
{case_section}
{gap_section}
{checklist_section}
{source_rule}
# 输出格式（严格 JSON）
{{
  "questions": [
    {{
      "id": "q01",
      "type": "choice",
      "dimension_id": "{selected_caps[0]['id']}",
      "source_ids": ["{source_example}"],
      "difficulty": "L1/L2/L3",
      "question": "简洁的知识点提问",
      "multi_select": false,
      "options": ["选项内容（不要 A. 前缀）", "选项内容", "选项内容", "选项内容"],
      "correct_answer": "A（只能写 A/B/C/D 中的一个字母）",
      "explanation": "为什么这个答案对，干扰项错在哪"
    }},
    {{
      "id": "q05",
      "type": "open",
      "dimension_id": "{selected_caps[0]['id']}",
      "source_ids": ["{source_example}"],
      "difficulty": "L2/L3",
      "question": "客户场景 + 现象 + 排查/建议要求",
      "scoring_rubric": ["得分点1", "得分点2", "得分点3"],
      "reference_answer": "完整参考答案要点"
    }}
  ]
}}

注意事项：
- options 数组里不要带 A. B. C. D. 前缀
- 中文出题
- dimension_id 必须从能力点 id 中选取
- {blueprint['num_choice']} 道选择题全部是单选题：multi_select=false，correct_answer 只写 A/B/C/D 中的一个字母
- 直接输出 JSON，不要 markdown 代码块"""

    llm = get_llm()
    resp = llm.chat(
        [
            {"role": "system", "content": f"你是 AWS {svc['name']} 培训专家，严格输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        model=model_id,
    )

    cleaned = _strip_code_fence(resp)
    try:
        data = json.loads(cleaned)
        questions = data.get("questions", []) if isinstance(data, dict) else []
    except json.JSONDecodeError:
        questions = []

    if not questions or not isinstance(questions, list):
        raise ValueError("题目生成失败，请重试")

    # 标准化 id
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError("生成题目未通过结构校验，请重试")
        if not q.get("id"):
            q["id"] = f"q{i+1:02d}"

    if not user_id:
        raise ValueError("缺少用户身份")
    allowed_caps = {c["id"] for c in selected_caps}
    fact_by_id = {item["id"]: item for item in load_glue_facts()} if service_id == "glue" else None
    _validate_questions(questions, allowed_caps, set(fact_by_id) if fact_by_id else None,
                        blueprint, recent_stems, allowed_caps if capability_ids and kind == "pre" else None)
    if fact_by_id:
        curated_urls = {doc.document_id.rsplit(":", 1)[-1]: doc.url
                        for doc in curated_fact_documents(service_id)}
        for question in questions:
            question["source_refs"] = [
                {"id": fact_id, "url": curated_urls.get(fact_id, fact_by_id[fact_id]["source"]),
                 "fact": fact_by_id[fact_id]["fact"]}
                for fact_id in question["source_ids"]
            ]

    from app.db import SessionLocal
    from app.models import QuestionSession

    session_id = session_id or uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(QuestionSession(id=session_id, user_id=user_id, service_id=service_id,
                               profile_id=profile_id,
                               model_id=model_id,
                               study_days=study_days, minutes_per_day=minutes_per_day,
                               kind=kind, prev_assessment_id=prev_assessment_id,
                               questions=questions,
                               blueprint={key: value for key, value in blueprint.items() if key != "expected"} |
                                         {"capability_ids": [c["id"] for c in selected_caps],
                                          "scope": "focused" if capability_ids else "comprehensive"}))
        db.commit()

    return session_id, questions
