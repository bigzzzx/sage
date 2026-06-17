# SAGE 项目当前状态（接续工作请先读这份）

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
| 部署 | EC2 (52.81.190.108) + Nginx 反向代理 |
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
│       │   └── AgentTracePanel.tsx  # AI 思考过程时间线
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
- [x] Agent Trace 展示（AI 思考过程时间线）
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

### EC2 (52.81.190.108)
- Nginx 反向代理：80 端口（`/api/*` → 后端 8000，其他 → 前端 3000）
- 后端：Python 3.11 + uvicorn，监听 127.0.0.1:8000
- 前端：Next.js 生产模式，监听 3000
- LLM：通过 SSH 反向隧道（EC2 localhost:9000 → 本地 → 内部 ELB）
- **隧道命令**（需在本地保持运行）：
  ```
  ssh -R 9000:internal-ai-tao-llm-apiserver-dev-1126944677.cn-northwest-1.elb.amazonaws.com.cn:80 -N -o ServerAliveInterval=30 ec2-zangxuan-linux1
  ```

### 预置账号
| 用户名 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | manager |
| demo | demo123 | member |
| alice | alice123 | member |
| bob | bob123 | member |
| carol | carol123 | member |

### LLM 配置
```
LLM_BASE_URL=http://127.0.0.1:9000/v1
LLM_MODEL=Qwen3.6-27B
```

---

## 5. 关键设计决策

| 决策 | 为什么 |
|---|---|
| 多 Agent 流水线 | 比单次大 prompt 更准：诊断→规划→反思，各司其职 |
| 按题目级别分评分维度 | L1 不该被"排查思路"维度拖累，L3 需要"前后对比"维度 |
| Checklist 注入出题 | 确保出题对齐内部培训标准，不跑偏 |
| Learning Path 注入规划 | 学习计划参考内部培训路径，不乱推荐 |
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

## 7. 常用命令

### EC2 操作
```bash
# SSH 连接
ssh ec2-zangxuan-linux1

# 重启后端
cd sage/backend && source venv/bin/activate
pkill -f uvicorn
nohup python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> /home/ec2-user/sage/logs/backend.log 2>&1 &

# 重启前端
fuser -k 3000/tcp
cd sage/frontend && nohup npm start >> /home/ec2-user/sage/logs/frontend.log 2>&1 &

# 重启 nginx
sudo systemctl restart nginx

# 查看日志
tail -50 sage/logs/backend.log
tail -50 sage/logs/frontend.log
```

### 本地操作
```powershell
# 启动 SSH 隧道（必须保持开着！）
ssh -R 9000:internal-ai-tao-llm-apiserver-dev-1126944677.cn-northwest-1.elb.amazonaws.com.cn:80 -N -o ServerAliveInterval=30 ec2-zangxuan-linux1

# 本地开发
cd backend && conda activate sage && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

### 更新代码到 EC2
```powershell
# 本地提交推送
git add -A && git commit -m "xxx" && git push origin main

# EC2 上（如果 GitHub 网络通）
cd sage && git pull origin main

# EC2 上（如果 GitHub 不通，用 scp）
scp backend/app/xxx.py ec2-zangxuan-linux1:/home/ec2-user/sage/backend/app/xxx.py
```

---

## 8. 给新对话窗口的指引

1. 读这份 `docs/PROJECT_STATUS.md`
2. 读 `docs/PROMPTS.md` 了解 5 个 prompt 设计
3. 不需要重读 case 文件 / checklist / learning path（除非要改）
4. 环境：Windows 本地开发 + EC2 部署，Python 用 conda env `sage`

**用户工作风格**：
- 直接、不绕弯，中文沟通
- 重大决策"先问后做"，不喜欢自作主张大改
- 重视细节体验
- 时间紧，倾向于"先动起来再调"
