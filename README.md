# SAGE — AI 驱动的 SE 自适应成长引擎

> SE Adaptive Growth Engine · 面向 SE 团队的 AI 能力评估与学习系统

SAGE 将能力评估、知识盲区诊断、个性化学习计划和后测验证串成一个闭环，帮助 SE 用数据了解自己的能力，也帮助管理者了解团队能力分布。

## 当前版本

当前版本已经完成从单一 Big Data 演示到多 Profile、多服务能力评估平台的扩展：

- 支持 Profile 注册、登录和切换，不同 Profile 显示对应的服务范围
- 覆盖 Big Data、Analytics、Database、Deployment、Networking & Security、SCD、Linux、Windows 等方向
- 已配置 9 个 Profile、44 个服务和 196 个能力点
- 支持动态出题、智能评分、知识盲区诊断、学习计划生成和后测验证
- 使用多 Agent 流水线完成诊断、规划和反思，并展示 Agent Trace
- 出题、评分和后测使用异步任务加轮询，避免长时间 LLM 请求触发 504
- 集成 RAG 检索能力，可从知识库中检索相关学习资料
- 管理员可查看按 Profile 过滤的团队能力看板

## 核心流程

```
选择 Profile → 选择服务与能力点 → AI 出题 → 提交答案并评分
                                          ↓
             能力雷达图 ← 盲区诊断 ← 个性化学习计划
                    ↓
                 学习后后测验证并对比能力变化
```

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 16 + React 19 + TypeScript + Tailwind CSS 4 + ECharts |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 |
| 数据库 | SQLite（开发与演示） |
| LLM | OpenAI 兼容协议，可配置云端或内部部署模型 |
| 检索 | RAG 服务与本地知识库 |

## 快速开始

### 环境准备

- Python 3.12
- Node.js 20+
- 可访问的 OpenAI 兼容 LLM 服务及 API key

### 配置后端

```powershell
Copy-Item backend/.env.example backend/.env
# 编辑 backend/.env，填写 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL
```

### 启动后端

```powershell
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API 文档：http://localhost:8000/docs

### 启动前端

```powershell
cd frontend
npm install
npm run dev
```

访问：http://localhost:3000

## 体验流程

1. 注册或登录账号。
2. 选择 Profile、服务和能力点。
3. 生成并完成测评题目。
4. 查看评分、能力雷达图、知识盲区和学习计划。
5. 在“我的档案”查看进行中的学习计划。
6. 完成学习后进入后测，比较前后能力变化。
7. 管理员进入团队看板，查看团队能力分布和培训建议。

## 项目结构

```
sage/
├── backend/                 # FastAPI 后端、认证、测评和 Agent 流水线
│   └── app/
│       ├── agents/          # 诊断、规划、反思和流程编排
│       ├── api/             # 认证、测评和异步任务 API
│       └── services/        # LLM、RAG、出题、评分和任务服务
├── frontend/                # Next.js 前端页面与可视化组件
├── data/
│   ├── cases/               # 真实案例数据
│   └── taxonomy/            # Profile、服务和能力定义
├── docs/                    # 部署、项目状态和 Prompt 文档
└── scripts/                 # 数据处理与测试脚本
```

## 相关文档

- [项目状态](./docs/PROJECT_STATUS.md)
- [部署指南](./docs/DEPLOYMENT.md)
- [Prompt 设计](./docs/PROMPTS.md)
- [RAG 说明](./docs/RAG.md)
- [项目概述](./项目概述.md)

## 安全提示

- `backend/.env`、数据库、日志和模型密钥不应提交到 Git。
- 请使用 `backend/.env.example` 创建本地配置，并通过环境变量管理密钥。
- 演示账号仅用于开发和演示，生产环境请更换密码和认证密钥。

## 后续方向

- 扩充各服务的真实案例、checklist、学习路径和文档白名单
- 完善跨轮次盲区追踪与循环学习
- 从 SQLite 迁移到 PostgreSQL
- 增加 Docker 化部署和更完善的生产环境配置
