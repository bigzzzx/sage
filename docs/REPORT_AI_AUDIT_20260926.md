# SAGE 报告质量 AI 预审（2026-09-26）

状态：**历史预审已作废，不能用来比较策略**。这是单次 AI 审查，不是两名独立 AWS Glue 人员标注。复核时发现 NAT 案例的题干只问公网 API，隐藏评分要点却要求区分 S3 Endpoint；输入口径不一致。样本已修订，旧运行的十份报告与逐报告标签仅供回溯具体缺陷，不是有效的实验结果。使用 `deepseek-flash` 的一次修正重跑曾因模型服务 HTTP 402 未完成；随后改用 `deepseek-v4-pro` 的[修正样本正式对照](REPORT_REVIEW_DECISION_20260926.md)已完成，不能与本页旧数据混用。

## 可复核发现

1. **样本口径错误**：网络案例的回答确实错误地认为 Glue ENI 会有公网 IP，且公有子网 + IGW 足够；但题干未要求 S3 Endpoint，隐藏 rubric 却要求。模型据 rubric 诊断 S3 遗漏，不能在这份旧样本中直接计为模型错误；真正的问题是对学员不公平的题目/评分要点错位。五组都继承同一份旧输入。[Glue VPC 网络文档](https://docs.aws.amazon.com/glue/latest/dg/start-connecting.html)、[S3 Endpoint 文档](https://docs.aws.amazon.com/glue/latest/dg/vpc-endpoints-s3.html)。
2. **共同事实错误**：Crawler 不负责清洗/转换，Data Catalog 存表元数据，这些方向正确；但共享诊断写成“清洗转换必须由 Glue ETL Job 完成”。[Athena CTAS](https://docs.aws.amazon.com/athena/latest/ug/ctas-insert-into-etl.html)和 [DataBrew recipe job](https://docs.aws.amazon.com/databrew/latest/dg/jobs.recipe.html)均是反例。应改为“由转换作业或工具完成，例如 Glue ETL Job”。
3. **个别验证方法不可靠**：网络案例双评审版建议用 `sts.get_caller_identity` 验证公网可达，但 STS 可经 [VPC Interface Endpoint](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sts_vpc_endpoint_create.html) 私网访问；它成功不证明 NAT 或公网可达。应使用明确的非 Endpoint 公网目标，并注明测试环境和前提。
4. **引用和实验可执行性**：一些报告的核心概念 URL 留空或用 S3/文件夹文档支撑更宽泛的 Catalog 定义；部分网络练习要求在 45 分钟内新建 NAT、改默认路由或移除 NAT，却未规定隔离 VPC、回滚与费用。Crawler 的单评审版提供了样本路径、时间分配、命令、观察点和权限不足时的替代步骤，相对更易执行，但未实际登录 AWS 运行。

## 探索性标签摘要

下表的事实/诊断为**两份报告的错误个数合计**，引用/可执行性为 0–2 的两例平均值；不是人工一致性或统计显著性结果。

| 策略 | 事实错误 | 诊断错误 | 引用支持 | 任务可执行性 |
| --- | ---: | ---: | ---: | ---: |
| 规则校验 | 1 | 0 | 1.0 | 1.0 |
| 单评审 | 1 | 0 | 1.5 | 1.5 |
| 双独立评审 | 2 | 0 | 1.0 | 1.0 |
| 多轮讨论 | 1 | 0 | 1.0 | 1.0 |
| 等调用量基线 | 1 | 0 | 1.0 | 1.0 |

旧 NAT 样本的 rubric 错位使这组比较失效；表格只保留为历史问题清单，**不能证明单评审优于其他策略**。Crawler 共同诊断仍含“必须由 Glue ETL Job 转换”的过度断言。新实验必须使用修订后的 fixture、增加更多脱敏样本并重新标注。费用未计算：旧试跑记录了 Token 与延迟，但没有经过核实的服务商单价。
