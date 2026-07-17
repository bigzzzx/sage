# SAGE — AI 驱动的 SE 自适应成长引擎

> SE Adaptive Growth Engine · PS AI Hackathon 内部效率提升赛道

把 SE 团队的能力培养，从"凭经验"变成"用数据"。

---

## 是什么

基于真实 case 数据驱动 AI，为每位 SE 生成动态更新的能力雷达图与个性化学习路径，也帮经理看清团队能力分布，把培训资源用在刀刃上。

**核心闭环**：

```
真实 case 建模 → AI 出题 → 智能评分 → 能力雷达图
                                          ↓
                          经理团队看板  ←  个性化学习计划
                                          ↓
                                      后测验证（雷达图前后对比）
```

---

## 当前 MVP 状态

聚焦 **Big Data 方向**：
- ✅ **AWS Glue**：5 个真实 case 建模出 7 个能力维度，AI 链路全跑通
- 🟡 **EMR / Athena / Redshift / Lake Formation / SageMaker / DynamoDB**：能力维度为示例数据，可正常体验测评流程

---

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 16 + React 19 + TS + Tailwind 4 + ECharts |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 |
| 数据库 | SQLite |
| LLM | 阿里云百炼 qwen-plus（OpenAI 兼容协议） |

---

## 快速开始

### 0. 环境准备

- **Python 3.12**：建议用 conda env（`conda create -n sage python=3.12`）
- **Node.js 20+**：用于前端
- **百炼 API key**：[https://bailian.console.aliyun.com](https://bailian.console.aliyun.com) 申请，免费额度

### 1. 配置 API key

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY
```

### 2. 启动后端

```powershell
cd backend
pip install -r requirements.txt
& "C:\Users\<USER>\.conda\envs\sage\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

访问 http://localhost:8000/docs 看 API。

### 3. 启动前端

```powershell
cd frontend
npm install
cmd /c "npm run dev"
```

访问 http://localhost:3000。

---

## 5 分钟体验

1. **首页** → 点"开始能力测评"
2. **测评配置**：选 Big Data → Glue → 选几个能力点 → 点"开始生成题目"
3. **答题**：AI 实时生成 4 选择 + 2 开放题（约 15-30 秒生成）
4. **提交评分**：等 30-60 秒 AI 多维度评分
5. **结果页**：查看雷达图 + 个性化 1 周学习计划 + 完整回顾
6. **我的档案**（`/profile`）：查看 Big Data Track 全 7 服务雷达
7. **经理看板**（`/dashboard`）：查看团队能力分布与培训建议
8. **后测验证**（`/post-test?prev=xxx`）：学完点"后测验证"，看雷达图前后对比

---

## 项目结构

```
AI Hackathon/
├── docs/
│   ├── PROJECT_STATUS.md   # 项目当前状态（接续工作必读）
│   └── PROMPTS.md          # 核心 Prompt 设计文档
├── backend/                # FastAPI 后端
├── frontend/               # Next.js 前端
├── data/
│   ├── cases/              # 真实 case JSON
│   └── taxonomy/           # 能力维度地图
├── scripts/                # 离线脚本（建模、出题、评分、e2e 测试）
└── 项目概述.md              # 最初的项目提案
```

详细说明见 [`docs/PROJECT_STATUS.md`](./docs/PROJECT_STATUS.md)。

---

## 文档索引

- 📋 [项目概述](./项目概述.md) — 最初的项目提案
- 📊 [项目当前状态](./docs/PROJECT_STATUS.md) — 接续工作必读
- 🤖 [Prompt 设计文档](./docs/PROMPTS.md) — 调优 LLM 输出参考
- 📁 [Case 数据规范](./data/cases/README.md) — 整理新 case 时参考

---

## 后续扩展方向

- 真实 case 库扩充：补 EMR / Athena 等服务的真实 case，让模拟数据变真实
- 多用户支持：当前所有操作 user_id 写死 `demo_user`
- 向量检索：学习资源对接真实 KB 文档（Embedding + 向量库）
- 数据库迁移：SQLite → PostgreSQL + alembic
- 容器化：Docker Compose 一键部署
