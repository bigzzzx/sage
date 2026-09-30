# 报告策略对照：实验协议与人工标注

这是**离线评测**，不会修改用户测评记录或生产工作流。当前用合成 Glue 答题样本；它们提供参考事实，但不是领域专家裁定的完整真值。不要把自动审稿意见当作人工标签。

首次完整试跑另有[单次 AI 来源核查预审](REPORT_AI_AUDIT_20260926.md)。旧 NAT 样本的隐藏 rubric 与题干不一致，这轮比较已作废；其标签只用于回溯问题，不得作为本协议的双人标签或最终实验结论。

修正样本后完成的正式对照及当前编排选择见[2026-09-26 工程结论](REPORT_REVIEW_DECISION_20260926.md)。其中逐报告分数仍是**单次 AI 预审**，不是下述双人盲评结果；两个合成样本不能证明统计优势。

## 实验单位与处理组

每个样本先用生产 `run_diagnosis` 和 `run_planning` 生成**一份共享初稿**；之后复制同一份初稿进入五组：

1. `rules`：单模型初稿 + `_plan_issues` 硬规则，不再调用模型。
2. `single_review`：一位证据审稿人；有意见时尝试一次计划修订。
3. `dual_review`：证据与教学两位独立审稿人；有意见时尝试一次计划修订。
4. `debate`：两位独立审稿人先各自评审，再各看对方意见并质疑一次；有意见时尝试一次计划修订。
5. `budget_repeat`：两位审稿人各做两次**不交换意见**的审查；其余规则与讨论组相同。这是“额外推理预算”基线。

模型、问题、答案、评分、原始诊断、原始计划在各组相同。`debate` 与 `budget_repeat` 各有四次评审调用，但 prompt/输出 Token 可能不同，必须检查总 Token 比值；超过 20% 不能称等预算。修订是否触发会影响总用量，因此同时报告调用量、Token、延迟、可选费用。共享诊断在各组**完全相同**，所以实验能检查诊断错误的绝对水平，却**不能识别评审策略是否改善诊断**；当前修订仅修计划。

## 执行

从 `backend` 目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m app.scripts.compare_report_strategies --model deepseek-flash --output ..\data\evals\runs\trial-001.json
```

脚本每组串行执行，分别记录共享生成和增量耗时/Token。输出既包含原始报告，也包含 `.blind.json` 盲评表。产物可能包含答题内容，**只用脱敏样本**，不要公开真实用户报告。再次运行换新文件名，防止覆盖。当前输入为 `data/evals/report_cases.json` 的小样本；`--limit 1` 可低成本试跑，不能用于结论。

接口失败时保留已完成样本和处理组，不要把部分结果当完整实验。服务恢复后用原模型、同一 fixture/seed/输出路径加 `--resume`，只重试失败或缺失组；首次失败后记录的 HTTP 状态码不会包含密钥或答题文本。若账户返回 402，先处理模型服务的余额/计费状态，**不要循环重试**。

费用需显式输入**运行当日核实过的**每百万 input/output Token 美元价格：`--input-usd-per-million X --output-usd-per-million Y`。未输入时费用为 `null`，不是零；供应商不返回 usage、调用失败或重试时 Token/费用也为 `null`。不包含网络传输、缓存计价等特殊折扣。延迟为墙钟耗时，包含重试。

不等人工标注也可只读查看运行指标（不会输出任何质量分数）：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.score_report_comparison --run ..\data\evals\runs\trial-001.json --metrics-only
```

## 双人盲评口径

让两位懂 AWS Glue 的人员独立填写每个 `.blind.json` 条目的 `annotations`，不要先看运行文件中的策略映射。每位填写 `annotator_id`、`labels`、`evidence_notes`；有争议时保留双方原值并另行仲裁，不要把模型审稿意见复制成标签。

- `factual_error_count`：报告中可由权威资料证伪的技术断言数；给出原句、资料链接与反证。资料不足的断言记在备注为“待核验”，不要强算事实错误。
- `diagnosis_error_count`：与用户答案不符、超出答题证据的缺口诊断数；注明题号、原答与问题诊断。纯粹遗漏可在备注中写明。
- `citation_support`：0=主要引用不能支持相邻断言/引用错误，1=部分支持但关键断言无充分证据，2=关键断言均有可定位的支持；URL 存在不等于支持。
- `task_actionability`：0=大部分任务无法按步骤复现或验证，1=可部分执行但缺配置/验收/时长依据，2=关键任务有具体步骤、可观察结果与合理预算。

填写后运行：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.score_report_comparison --run ..\data\evals\runs\trial-001.json --blind ..\data\evals\runs\trial-001.blind.json
```

汇总仅在**全部报告由两个不同标注人完整标注**后运行；输出各组均值、与规则组的配对差、双人完全一致率、讨论/等调用量基线的 Token 匹配情况。当前两个合成样本不足以做显著性或产品收益结论；还需要扩展真实脱敏案例、预先定义最小有意义改进、处理标注分歧，并在不同模型/随机种子重复。只有在人审质量增益稳定且预算匹配时，才考虑把新审稿策略接入用户工作流。
