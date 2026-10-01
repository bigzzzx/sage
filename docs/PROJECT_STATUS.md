# SAGE 项目当前状态（接续工作请先读这份）

> 2026-09-30 本地更新：报告到针对性再测/同服务工单的入口、用户纠错与管理员复核、学习任务状态与人工验收、知识条目重复发布拦截/版本替换/增量向量索引、培训任务、运行指标、历史筛选和报告目录已接入。内置浏览器已用普通成员和管理员实际登录，验收首页、档案、历史筛选、测评/实战入口、管理页及一条真实纠错的提交→采纳→成员可见闭环；修复同源 API 转发、两处水合问题和管理页 Profile 选项。隔离数据库自动测试 116 项及 TypeScript/ESLint 通过。隔离临时库的 DeepSeek Flash 真实测评闭环成功，复测仍发现来源、盲区映射和时间预算问题，质量门禁保持 `needs_review`，不可宣称计划均可直接执行。生产上线前仍需备份、部署环境验收和更大样本的专业内容评审。下文旧架构、部署和“当前状态”均为历史快照。

> 2026-09-26 更新：前测评分后的诊断、规划、审查链路已接入 LangGraph SQLite 检查点；异步测评请求改为保存可重放负载，报告页支持失败后继续生成计划。工作范围及生产限制见 [评估工作流迁移记录](./WORKFLOW_MIGRATION.md)。下文旧技术栈、部署和任务机制为历史描述，不应视为当前验收结论。

> 2026-09-23 本地代码更新：新增服务端鉴权隔离、题目会话与任务结果持久化、两种 Glue 练习场景、学习完成证据、历史报告、管理员/成员初始化、SQLite 在线备份和 CI 配置。本机已通过 17 项后端验收测试、前端生产构建及浏览器练习闭环；CI 尚未推送验证，真实 LLM 测评端到端和历史 EC2 部署状态未在本轮复验。详见 [发布就绪清单](./RELEASE_READINESS.md)。以下 2026-06-16 内容为历史快照，涉及服务数量、模型和云端状态的描述不可视为当前事实。

> 最后更新：2026-06-16
> 用途：在新对话窗口快速接续工作。读完这份就能进入工作状态。

---

## 0. 一分钟快速理解

**项目名**：SAGE — SE Adaptive Growth Engine
**赛道**：PS AI Hackathon 内部效率提升
**核心想法**：用 AI 多 Agent 协作，为 SE 做能力评估 → 盲区诊断 → 个性化学习计划 → 后测验证 → 循环提升。

**当前阶段**：MVP 基本功能完成，已部署到 EC2，正在打磨细节和扩展内容。

---

## 1. 技术架构

### 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 16 + React 19 + TypeScript + Tailwind 4 + ECharts |
| 后端 | Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy 2 |
| 数据库 | SQLite（`backend/sage.db`） |
| LLM | 内部部署 Qwen3.6-27B（OpenAI 兼容协议） |
| 部署 | 历史试验环境：EC2 + Nginx 反向代理；当前部署状态需重新核实 |
| LLM 通路 | SSH 反向隧道（EC2:9000 → 本地 → 内部 ELB） |

### Multi-Agent 流水线

```
[出题 Agent]          question_gen.py        动态生成 6选择+3开放
       ↓
[评分 Agent]          assessment.py          按 L1/L2/L3 不同维度打分
       ↓
[诊断 Agent]          agents/diagnosis.py    每答错题独立诊断知识盲区
       ↓
[规划 Agent]          agents/planning.py     基于盲区+白名单文档池+Learning Path 写 5 天计划
       ↓
[反思 Agent]          agents/reflection.py   质检计划覆盖度+内容对齐度+质量
       ↓
[完成 + Trace 持久化]  全程 AgentStep 记录到 DB
```

### 异步任务机制

所有 LLM 慢操作（出题/评分/后测）使用异步任务+轮询模式：
- `POST /generate` → 立即返回 `task_id`
- 前端每 2s 轮询 `GET /task/{task_id}`
- 任务完成返回结果，避免中间层超时 504

---

## 2. 目录结构

```
sage/
├── docs/
│   ├── PROJECT_STATUS.md      # 本文件
│   ├── DEPLOYMENT.md          # EC2 部署指南
│   └── PROMPTS.md             # 5 个核心 Prompt 设计文档
├── backend/
│   ├── .env                   # LLM 配置（不入 Git）
│   ├── requirements.txt
│   ├── sage.db                # SQLite（不入 Git）
│   └── app/
│       ├── main.py            # FastAPI 入口
│       ├── config.py          # 环境变量加载
│       ├── db.py              # SQLAlchemy + 自动加列迁移
│       ├── models.py          # ORM: Assessment + User 表
│       ├── api/
│       │   ├── assessment.py  # 测评 API（异步任务模式）
│       │   └── auth.py        # 认证 API（登录/Profile 切换）
│       ├── schemas/
│       │   └── assessment.py  # Pydantic 模型（含 KnowledgeGap/AgentStep）
│       ├── agents/
│       │   ├── common.py      # 共享工具（JSON解析/文档池/Learning Path加载）
│       │   ├── diagnosis.py   # 诊断 Agent
│       │   ├── planning.py    # 规划 Agent
│       │   ├── reflection.py  # 反思 Agent
│       │   └── orchestrator.py # 编排器
│       └── services/
│           ├── llm.py         # LLM 客户端（含 chat_traced）
│           ├── taxonomy.py    # Taxonomy 加载
│           ├── question_gen.py # 出题（含 checklist 注入）
│           ├── assessment.py  # 评分+多Agent流水线编排
│           └── tasks.py       # 异步任务管理
├── frontend/
│   ├── .env.local             # NEXT_PUBLIC_API_BASE=（空，走 nginx 代理）
│   └── src/
│       ├── lib/
│       │   ├── api.ts         # 后端 API 封装（含 pollTask 轮询）
│       │   └── auth.ts        # 认证工具（localStorage）
│       ├── components/
│       │   ├── RadarChart.tsx
│       │   ├── TrackRadarChart.tsx  # 含 hover 弹出 capability 雷达
│       │   ├── HeatmapChart.tsx
│       │   ├── LearningPlanCard.tsx # 学习计划卡片（含盲区标签+预期产出）
│       │   ├── DiagnosisPanel.tsx   # 知识盲区诊断展示
│       │   └── AgentTracePanel.tsx  # 工作流步骤记录
│       └── app/
│           ├── login/page.tsx
│           ├── select-profile/page.tsx
│           ├── page.tsx             # 首页（按角色区分）
│           ├── assessment/page.tsx  # 测评（按 Profile 过滤服务）
│           ├── result/page.tsx      # 结果（含诊断+学习计划+trace）
│           ├── post-test/page.tsx
│           ├── profile/page.tsx     # 我的档案（含进行中计划）
│           └── dashboard/page.tsx   # 经理看板（按 Profile 过滤）
└── data/
    ├── cases/                 # 19 个真实 case（Glue/EMR/Athena/MWAA/MSK/OpenSearch/QuickSight/SageMaker/DynamoDB/LakeFormation）
    └── taxonomy/
        ├── tracks.json        # Track 索引（Big Data + Analytics）
        ├── services/          # 12 个 service 的 capability 定义
        ├── checklist/         # 7 个 service 的内部培训考核要点
        └── learning_path/     # 4 个 service 的学习路径
```

---

## 3. 已完成功能

### 核心链路
- [x] 登录（账号密码） + Profile 选择（Big Data / Analytics 可用，其他占位）
- [x] 角色区分：员工（测评+档案）vs 管理员（团队看板）
- [x] 动态出题：6 选择 + 3 开放，L1/L2/L3 各 2+1，参考 checklist 考点池
- [x] 评分：按题目级别用不同维度（L1=3维 / L2=4维 / L3=5维）
- [x] 诊断 Agent：每答错题独立诊断盲区，参考 checklist 定位知识点
- [x] 规划 Agent：基于盲区+白名单文档池+Learning Path 生成 5 天学习计划
- [x] 反思 Agent：质检计划（覆盖度+对齐度+质量）
- [x] 后测：基于前测盲区针对性出题验证
- [x] 雷达图：Track 级（hover 弹 capability 级）+ 单 service 级
- [x] 进行中的学习计划（按 Profile 过滤，后测完自动归档）
- [x] 团队看板（按 Profile 过滤服务，只有管理员可见）
- [x] Agent Trace 展示（工作流步骤记录，不是模型思维链）
- [x] 异步任务+轮询（避免 504 超时）
- [x] URL 白名单文档池（Glue 34 条已策展，其他服务暂空）
- [x] 自动加列迁移（schema 变了不用删 DB）

### 数据
- [x] 19 个真实 case（覆盖 10 个服务）
- [x] 7 份 checklist（EMR+Hadoop/Hive/Spark/HBase/Glue/DynamoDB/SageMaker）
- [x] 4 份 Learning Path（EMR/Glue/DynamoDB/SageMaker）
- [x] 12 个 service 的 capability 定义（Big Data 7 个 + Analytics 5 个）
- [x] Glue 7 个 capability 有完整 doc_refs 白名单（32 条真实 AWS CN 文档 URL）

---

## 4. 部署状态

### 历史 EC2 试验环境（配置已脱敏，不能作为现行部署说明）
- Nginx 反向代理：80 端口（`/api/*` → 后端 8000，其他 → 前端 3000）
- 后端：Python 3.11 + uvicorn，监听 127.0.0.1:8000
- 前端：Next.js 生产模式，监听 3000
- LLM：曾通过 SSH 反向隧道接入内部推理服务；真实主机名和连接信息不在仓库公开。

### 演示账号
新安装不会自动创建演示账号；开发和生产环境都应通过管理命令创建管理员并设置独立强密码。已有本地数据库中的历史账号不受此变更影响。

### LLM 配置
```
LLM_BASE_URL=http://127.0.0.1:9000/v1
LLM_MODEL=Qwen3.6-27B
```

---

## 5. 关键设计决策

| 决策 | 为什么 |
|---|---|
| 自研角色分工工作流 | 诊断→规划→反思→最多一次修订，可追踪；尚未证明比单次提示词更准确 |
| 按题目级别分评分维度 | L1 不该被"排查思路"维度拖累，L3 需要"前后对比"维度 |
| Glue 官方考点出题 | 默认使用已策展的公开事实并绑定来源 ID；旧内部 Checklist 不再进入 Glue 出题 |
| Glue 官方资料规划 | 公开事实与官方文档优先；其他服务仍可使用内部 Learning Path |
| URL 白名单 | LLM 不能编造 URL，只能从策展池选 |
| 异步任务+轮询 | LLM 慢（100s+），避免中间层 504 |
| SSH 反向隧道 | EC2 不在 LLM 内部 ELB 的 VPC，通过本地中转 |
| Profile = Track | 用户选的 Profile 决定看到的服务范围 |

---

## 6. 已知问题 / TODO

### 🔴 P0（影响演示）
- [ ] SSH 隧道断了 LLM 就不可用（需手动保持本地窗口开着）
- [ ] 出题/评分等操作需要 100 秒+（模型吞吐慢）

### 🟡 P1（建议做）
- [ ] 学习闭环：后测后基于新盲区自动生成新一轮计划（循环学习）
- [ ] 盲区延续追踪：跨轮标记"仍未掌握(第N次)"
- [ ] mentee 成长时间线（给 mentor/admin 看的历史曲线）
- [ ] 其他 service 的 doc_refs 白名单策展（目前只有 Glue 有）
- [ ] Analytics 5 个服务的 checklist + learning path

### 🟢 P2（时间充裕再做）
- [ ] 扫码登录
- [ ] 运行时 MCP 集成（白名单未命中走 AWS CN Docs MCP 拉取）
- [ ] 多选题支持
- [ ] 学习进度勾选（每天完成打勾）
- [ ] Docker 化部署

---

## 7. 开发与部署

本地开发命令见项目根目录的 `README.md`；远端部署前需重新确认环境、密钥、数据库备份与迁移方式。本文件中的旧部署快照不能直接作为上线操作手册。
- 重视细节体验
- 时间紧，倾向于"先动起来再调"
