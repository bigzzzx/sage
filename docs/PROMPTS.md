# SAGE 核心 Prompt 设计文档（v8 — Multi-Agent）

> 用途：调题目质量、调评分严格度、调诊断准确度、调学习计划风格 时的参考
> 配套：调试时打开 `backend/llm_debug.log` 看实际 prompt + 回复

---

## 1. 流水线总览（v8 起改为多 Agent）

```
[出题 Agent]          question_gen.py
       ↓
[评分 Agent]          assessment.py._score_open_question + 选择题硬比对
       ↓
[诊断 Agent]          agents/diagnosis.py    每答错的题独立调一次，输出结构化盲区列表
       ↓
[规划 Agent]          agents/planning.py     基于盲区 + 白名单文档池，写 5 天计划
       ↓
[反思 Agent]          agents/reflection.py   质检覆盖度（不重新生成，只评分报告）
       ↓
[完成 + Trace 持久化]  全程 AgentStep 记录到 DB
```

每个 agent 独立 prompt 文件、独立调用、独立 trace。失败可单独兜底，不会拖垮整个流程。

---

## 2. Prompt 索引

| Prompt | 文件位置 | 输出 | 触发时机 |
|---|---|---|---|
| **出题** | `services/question_gen.py` | 选择题 + 开放题 | 前/后测点"开始生成" |
| **评分** | `services/assessment.py` 的 `_SCORING_PROMPT` | 5 维度打分 + level + feedback | 每道开放题 |
| **诊断** | `agents/diagnosis.py` 的 `_DIAG_PROMPT` | KnowledgeGap[]（每题最多 4 条） | 答错或低分题，**每题独立调** |
| **规划** | `agents/planning.py` 的 `_PLAN_PROMPT` | 5 天 LearningPlan，task 必须 cite gap_id | 诊断完成后一次调用 |
| **反思** | `agents/reflection.py` 的 `_REFL_PROMPT` | coverage_score + uncovered_gap_ids + 对齐评估 | 规划完成后一次调用 |

---

## 3. 出题 Prompt（不变）

设计意图、规则、调优 tips 见之前版本。本版本未做改动。

---

## 4. 评分 Prompt（不变）

5 维度（accuracy/completeness/diagnostic_approach/depth/practicality）1~5 分。

---

## 5. 诊断 Prompt（v8 新增 — 灵魂）

### 设计意图

让 LLM 像 senior SE 给后辈做 review，**精准识别这名 SE 在这道题上暴露的具体知识盲区**，不是泛泛"理解不深"。

### 输入

- 题目 + rubric + 参考答案 + 用户答案 + 用户得分
- 对应 capability 的描述 + L1/L2/L3 等级
- 该 capability 的策展文档池（白名单）

### 输出（JSON 数组）

```json
[
  {
    "title": "SG 自引用规则",
    "misunderstanding": "用户用 NACL 控制 Glue 内部通信",
    "correct_understanding": "Glue 多个 ENI 之间通信靠 SG 自引用，NACL 是无状态的不能解决",
    "evidence_quote": "我用了 NACL...",
    "severity": "major",
    "suggested_doc_urls": ["https://docs.amazonaws.cn/.../setup-vpc-for-glue-access.html"]
  }
]
```

### 关键约束

- severity：critical / major / minor 三档
- suggested_doc_urls 必须严格来自该 capability 的白名单（后端二次校验）
- 答得完美时输出 `[]`，每题最多 4 条

### 调优 tips

- 如果诊断太宽松（"理解不够全面"这种水），prompt 加更狠的指令："要找到具体哪个细节错，不是泛泛"
- 如果挑刺过头（minor 太多），可在 prompt 加"宁少勿乱，每题不超过 3 条"
- 如果 evidence_quote 失真，强调"必须从用户答案里**原文截取**，不允许改写"

---

## 6. 规划 Prompt（v8 重写）

### 输入

- 服务名、总体评级、各能力得分
- **所有诊断盲区（带 gap_id、severity、misunderstanding 等）**
- 与盲区相关的 capability 的策展文档池

### 关键设计

1. 每个 task 必须 `targets_gap_ids` 字段，cite 至少一个真实 gap_id
2. 所有 critical / major 盲区必须被至少一个 task 覆盖
3. 由浅入深：Day 1~2 reading/review，Day 3~4 lab，Day 5 quiz
4. URL 严格白名单，未命中清空

### 后端兜底

- weekly_plan 长度强制截到 1
- time_minutes 夹到 [60, 120]
- targets_gap_ids 中无效的 gap_id 自动剔除
- concepts[].url 不在白名单一律清空

---

## 7. 反思 Prompt（v8 新增）

### 设计意图

防止规划 agent 自欺欺人地"声称针对了 X 盲区，实际内容跑偏"。让另一个 LLM 实例做 QA。

### 输出

```json
{
  "coverage_score": 4,
  "uncovered_gap_ids": ["gap_q5_2"],
  "weak_alignment_tasks": [
    {"day": "Day 3", "issue": "声称针对 SG 自引用，但内容讲了 NAT，跑偏"}
  ],
  "summary": "整体覆盖良好，建议补充 SG 自引用实操"
}
```

### 当前阶段不触发重生成

第一版只做"评分 + 报告"，前端可选展示。如果质量不够再加"重生成一次"逻辑（避免演示当天抽风）。

---

## 8. URL 白名单文档池（v7 起 + v8 沿用）

每个 service 在 `data/taxonomy/services/{service}.json` 的 `capabilities[].doc_refs` 维护策展 URL。

诊断 agent 用对应 capability 的子池；规划 agent 用所有相关 capability 的合集池。

### 长期路径（v9 设想）

- 启动 MCP client 子进程（awslabs/aws-documentation-mcp-server，配 AWS_DOCUMENTATION_PARTITION=aws-cn）
- 白名单未命中时走 `read_documentation(url)` 实时拉
- 缓存到 SQLite，下次直接读
- 自动巡检（cron）定期校验链接相关性

当前阶段 v8 + 策展白名单已经够用。

---

## 9. Agent Trace

每个 agent 调用都会输出一条 `AgentStep`：
```python
AgentStep(
    agent="diagnosis",
    label="诊断题目 q3",
    input_summary="capability=glue_network, score=2.0/5",
    output_summary="识别到 2 个盲区",
    elapsed_ms=4700,
    timestamp="2026-05-29T...",
    status="ok",
)
```

存进 DB 的 `assessments.agent_trace` 字段，前端 `<AgentTracePanel>` 折叠展示，演示时讲"AI 思考过程"。

---

## 10. 调试 / 验证清单

### 看实际 prompt + 回复

```powershell
type backend\llm_debug.log
```

### 关闭日志

```powershell
$env:LLM_DEBUG = "0"
```

### 单 agent 测试

可以在 `backend/scripts/` 下写小脚本，单独调用某个 agent，跳过完整流程。

### 演示前必跑

- [ ] 删 sage.db 让 demo_user 干净
- [ ] 跑一次完整测评，确认：
  - 诊断 agent 输出有值（盲区不为空）
  - 学习计划每个 task 都 cite 了 gap_id
  - URL 都是 docs.amazonaws.cn 真实页面（点开看）
  - AgentTracePanel 展示完整 5+ 步
- [ ] llm_debug.log 大致符合预期
- [ ] 后测一次跑通（prev_capability_radar 对比正常）
