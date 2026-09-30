# Glue 出题质量基准（2026-09-23）

## 边界与结论

本基准用 12 道来源于 AWS 官方文档的单选事实题比较已配置模型，并用 SAGE 实际开放题评分函数重复评分同一强答案、一次弱答案。题库位于 `data/evals/glue_public_facts.json`，可复跑脚本为 `backend/app/scripts/evaluate_glue_quality.py`。这是小样本烟测，不是 AWS 认证、生产准确率或评分公平性证明。

本机实测（选项用固定种子重排，同一试卷；单次运行）：

| 模型 | 事实题 | 批量答题耗时 | 强答案三次评分 | 弱答案评分 | 强答案平均评分耗时 |
|---|---:|---:|---:|---:|---:|
| `deepseek-flash` | 12/12 | 3.3 秒 | 5.0 / 5.0 / 5.0 | 1.0 | 7.3 秒 |
| `deepseek-v4-pro` | 12/12 | 12.4 秒 | 5.0 / 5.0 / 5.0 | 1.0 | 32.6 秒 |

这组简单事实题没有拉开正确率差距；在本机样本中 Flash 更快，不意味着所有真实测评都更快或更准确。更有区分力的场景题、边界条件题和盲评人工标注仍需扩充。

既有真实生成的两套 Glue 题共 18 道，按公开文档初审：9 道有公开依据，5 道涉及 JES/Crawler 内部执行阶段而未找到可公开核验的依据，4 道标准答案存在公开文档冲突或过度确定的风险。内部知识不因此被断言为假，但未经内部资料持有人核验前，不宜作为面向一般用户的标准答案。

风险样例：

- 一道题的参考答案认为 Glue Job 在公有子网加 Internet Gateway 可直接访问公网；[AWS Glue VPC 文档](https://docs.aws.amazon.com/glue/latest/dg/start-connecting.html)说明 Glue ENI 只有私有 IP，访问公网通常还需要 NAT 出口。
- 一道题把 `glue:CreateTask/RunTask` 写成公开 IAM 标准动作；公开 [StartJobRun API](https://docs.aws.amazon.com/glue/latest/webapi/API_StartJobRun.html) 不支持据此确认这些动作为标准答案，需要内部依据。
- 一道题由 OOM 现象直接断言特定 join key 倾斜，另有一道题断言 Crawler 固定默认 worker 数；两者均缺少足以作标准答案的依据。

因此 Glue 默认出题已改为仅向模型提供 `glue_public_facts.json` 的可追溯公开考点，不再注入未经核验的内部 checklist 或案例 RAG。每道新 Glue 题还必须输出 1~3 个 `source_ids`；服务端拒绝不在策展题库内的 ID，并自行生成官方出处链接，交卷后可查看。Glue 诊断和学习计划也优先使用同一公开事实包，避免旧 checklist/RAG 重新注入未经核验的事实。其他服务出题逻辑不变。

来源绑定仅验证“引用了存在的官方事实 ID”，不能机器证明题干、选项、解释、参考答案与该事实在语义上吻合。生成仍是 LLM 自由文本；上线前仍需题目级人工审核和更大规模交叉评测。旧测评会话不会被自动改写，应作为历史试验数据看待。

已绑定的事实还会进入开放题评分和盲区诊断提示词，并提醒模型在参考答案冲突时以可核验事实为准；这是降低错误传播的约束，不是独立的答案正确性裁判。学习计划的反思结果会触发最多一次修订，未解决的问题明确标为 `needs_review`，不会伪装为验收通过。

早期使用 `deepseek-flash` 生成的一套 9 题通过结构校验并写入演示会话 `75201b2536084866a2746d22d0e0d8c4`，但它早于逐题来源绑定；6 道选择题都围绕公开题库，开放题仍扩展到了 IAM 执行角色和 Spark 数据倾斜等题库未直接覆盖的知识点。旧会话没有被回填假来源。下一步仍需独立语义核验或人工发布审核。

## 复验

```powershell
cd backend
python -m app.scripts.evaluate_glue_quality --models deepseek-flash deepseek-v4-pro --repeats 3
python -m unittest discover -s tests -q
python -m app.scripts.smoke_assessment_workflow --model deepseek-flash
```

模型响应耗时按每次调用记录；单次批量事实题耗时不能与应用的完整 9 题生成延迟等同。评分强/弱答案只是一个固定 VPC 网络场景，不能外推至所有能力点、难度或人群。
