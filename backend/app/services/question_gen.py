"""动态出题服务（v2 - 基于 Service）。

接收 Service ID + Capability ID + 难度，调用 LLM 实时生成题目。
- Glue（is_real=true）：会附上真实 case 摘要作为素材
- 其他服务（is_real=false）：仅基于 capability 定义和 LLM 自身知识出题
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.services.llm import get_llm
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


# 缓存：session_id -> {service_id, capability_ids, questions}
_session_store: dict[str, dict] = {}


def get_session(session_id: str) -> dict | None:
    return _session_store.get(session_id)


def get_session_questions(session_id: str) -> list[dict] | None:
    s = _session_store.get(session_id)
    return s["questions"] if s else None


def generate_questions(
    service_id: str,
    capability_ids: list[str] | None = None,
    num_choice: int = 6,
    num_open: int = 3,
    difficulty: str = "",
    post_test_gap_hints: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """基于 Service 动态生成题目。固定 6 选择 + 3 开放（L1/L2/L3 均匀分布）。返回 (session_id, questions_list)。"""
    svc = get_service(service_id)
    if not svc:
        raise ValueError(f"Unknown service: {service_id}")

    all_caps = svc.get("capabilities", [])
    if capability_ids:
        selected_caps = [c for c in all_caps if c["id"] in capability_ids or c["name"] in capability_ids]
    else:
        selected_caps = all_caps

    if not selected_caps:
        selected_caps = all_caps  # 兜底

    cap_context = "\n".join(
        f"【{c['name']}】（id={c['id']}）{c['description']}"
        + f"\n  L1: {c['levels']['L1']}"
        + f"\n  L2: {c['levels']['L2']}"
        + f"\n  L3: {c['levels']['L3']}"
        for c in selected_caps
    )

    case_summaries = _load_case_summaries(service_id)
    case_section = f"\n# 真实 Case 素材（用于灵感，不要照抄）\n{case_summaries}\n" if case_summaries else ""

    # 加载 checklist 考点池
    checklist_text = _load_checklist(service_id)
    checklist_section = f"""
# 考点范围（来自内部 Knowledge Check List，出题必须覆盖这些知识点）

以下是该服务内部培训的考核要点，按 L1/L2/L3 分级。出题时请确保：
- L1 题考 [L1] 标注的知识点
- L2 题考 [L2] 标注的知识点
- L3 题考 [L3] 标注的知识点
- 不要出超出以下范围的题目

{checklist_text}
""" if checklist_text else ""

    # 后测盲区注入
    gap_section = ""
    if post_test_gap_hints:
        gap_lines = "\n".join(post_test_gap_hints)
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

    difficulty_hint = "难度分布固定：选择题 L1×2 + L2×2 + L3×2 = 6 道；开放题 L1×1 + L2×1 + L3×1 = 3 道。每个难度级别的题必须严格标注 difficulty 字段。"

    prompt = f"""你是 AWS {svc['name']} 培训专家。请生成一套测评题目。

# 题目数量与难度（固定，不可更改）
- 选择题 6 道：L1 难度 2 道、L2 难度 2 道、L3 难度 2 道
- 开放题 3 道：L1 难度 1 道、L2 难度 1 道、L3 难度 1 道
- 共 9 道题
- 每道题必须设置 dimension_id（从下方能力点 id 中选取）和 difficulty（L1/L2/L3）
- 选择题尽量覆盖不同的能力点，避免都聚焦在同一类

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

**参考示例（AWS 内部考试选择题，注意区分单选与多选的出题风格差异）：**

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

示例 S3（L1 单选 - 配置陷阱）：
  题干：When run an Athena query select * from glue_knet_111, did it return the values? If not, why?
  选项：
  - Partitions need to be added to the table manually.
  - Include path does not end with "/".（正确）
  - Crawler will fail to create a table in this configuration.
  分析：考一个具体配置细节导致的唯一根因

示例 S4（L3 单选 - 内部实现 / 架构细节）：
  题干：Which crawler command accesses customer's resource (like RDS)?
  选项：
  - WORKER and FINALIZER need to access customer resources.
  - All command access customer resources.
  - Only WORKER access customer resources.（正确）
  - START_CRAWL and WORKER access customer resources.
  分析：考的是 Crawler 内部执行阶段（START_CRAWL / WORKER / FINALIZER）中哪个阶段真正碰客户数据。这属于 AWS 内部架构知识，只有深入理解底层才知道

### 多选题风格特征（当前仅作为理解参考，本次只出单选题）
- 问的是"有哪些方式/有哪些行为"，正确答案 2~3 个
- 题干问法："Which of the following can be used to...?"、"What actions does X take?"（Choose all that apply）
- 选项之间不互斥，多个可以同时成立

示例 M1（L1 多选 - 支持范围）：
  题干：What data sources does Crawler support?（Choose all that apply）
  选项：Delta Lake（正确） / S3（正确） / DynamoDB（正确） / Microsoft Access（错误）

示例 M2（L1 多选 - 行为机制）：
  题干：When a Crawler runs, what action it takes to interrogate a data store?（Choose all that apply）
  选项：
  - Writes metadata to the AWS Glue Data Catalog（正确）
  - Classifies the data（正确）
  - Groups the data into tables or partitions（正确）
  - Transfers the data into S3（错误 - 这是 Job 做的）

示例 M3（L2 多选 - 安全最佳实践）：
  题干：How can we prevent the exposure of credentials while reading data from JDBC data store in a Glue ETL job?（Choose all that apply）
  选项：
  - Use SecretManager to store the credentials（正确）
  - Fetch the credentials using GetConnection API or extract_jdbc_conf() inside the job（正确）
  - Populate Glue Data Catalog with help of crawler and use from_catalog() method in the Glue ETL job（正确）

示例 M4（L2 多选 - API 配置方法）：
  题干：Which of the following options can be used to enable parallel reads with JDBC tables?（Choose all that apply）
  选项：
  - Pass the parameter along with rest of the connection_options（正确）
  - Pass parameters in additional_options while using from_catalog() method.（正确）
  - Set parameters as key-value pairs in the parameters field of your table structure（正确）

**从以上示例中总结出的选择题设计模式（必须遵循）：**
- **当前只出单选题**（multi_select 全部设为 false，correct_answer 只写一个字母）
- 单选题的核心：**问的是一个唯一事实**，干扰项来自同维度不同对象的真实描述
- L1 单选围绕"是什么 / 产出什么 / 某个具体事实"
- L2 单选围绕"某个配置的正确做法 / 两种方式的核心区别 / 某个行为的唯一原因"
- L3 单选围绕"AWS 内部架构细节（如 Crawler 的 command 阶段、Job 的 executor 生命周期）/ 性能调优的唯一最佳方案 / 故障排查思路中的关键判断点 / 极端场景下唯一可行方案"
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
  - "Crawler 的执行过程是什么？（start_crawl → worker → finalizer → stop_crawl）"
  - "Dynamic Frame 与 Data Frame 的区别？"
  - "Spark 的提交流程（submit → driver → executor）"
  - "Crawler 跑 worker 执行情况下数据是如何分发和处理的？"
  - "Glue parquet 与 S3 原生 parquet 的区别，看看什么标记？"
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
# 输出格式（严格 JSON）
{{
  "questions": [
    {{
      "id": "q01",
      "type": "choice",
      "dimension_id": "{selected_caps[0]['id']}",
      "difficulty": "L1/L2/L3",
      "question": "简洁的知识点提问",
      "multi_select": false,
      "options": ["选项内容（不要 A. 前缀）", "选项内容", "选项内容", "选项内容"],
      "correct_answer": "A/B/C/D（单选写一个字母，多选写多个如 ABD）",
      "explanation": "为什么这个答案对，干扰项错在哪"
    }},
    {{
      "id": "q05",
      "type": "open",
      "dimension_id": "{selected_caps[0]['id']}",
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
- 选择题可以是单选或多选：多选题设 multi_select=true，题干注明"Choose all that apply"或"选出所有正确项"，correct_answer 写多个字母如 "ABD"
- 单选题设 multi_select=false，correct_answer 只写一个字母
- 直接输出 JSON，不要 markdown 代码块"""

    llm = get_llm()
    resp = llm.chat(
        [
            {"role": "system", "content": f"你是 AWS {svc['name']} 培训专家，严格输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
    )

    cleaned = _strip_code_fence(resp)
    try:
        data = json.loads(cleaned)
        questions = data.get("questions", [])
    except json.JSONDecodeError:
        questions = []

    if not questions:
        # 兜底：极简题目（避免完全空白）
        questions = [{
            "id": "q01",
            "type": "open",
            "dimension_id": selected_caps[0]["id"],
            "difficulty": "L2",
            "question": f"请描述你对 AWS {svc['name']} 中【{selected_caps[0]['name']}】的理解，以及典型应用场景。",
            "scoring_rubric": [f"覆盖 {selected_caps[0]['name']} 核心概念", "结合实际场景说明", "提及最佳实践"],
            "reference_answer": selected_caps[0].get("description", ""),
        }]

    # 标准化 id
    for i, q in enumerate(questions):
        if not q.get("id"):
            q["id"] = f"q{i+1:02d}"

    session_id = uuid.uuid4().hex[:12]
    _session_store[session_id] = {
        "service_id": service_id,
        "capability_ids": [c["id"] for c in selected_caps],
        "questions": questions,
    }

    return session_id, questions
