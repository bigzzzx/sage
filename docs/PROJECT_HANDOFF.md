# SAGE 项目交接与后续路线

> 文档用途：新对话、新开发者或面试准备时，快速理解当前项目。
> 当前版本：多 Agent 能力评估 + ChromaDB RAG 已接入。

## 1. 项目定位

SAGE（SE Adaptive Growth Engine）是面向技术支持工程师的 AI 能力评估与学习规划系统。

核心闭环：

```text
选择技术方向 → 动态生成测评题 → 用户答题 → 评分
→ 识别知识盲区 → 生成个性化学习计划 → 后测验证 → 追踪成长
```

项目目前以 AWS 数据工程和分析服务作为领域内容，主要服务包括 Glue、S3、Athena、DynamoDB、EMR、Lake Formation、MSK、MWAA、OpenSearch、QuickSight 和 SageMaker 等。

## 2. 当前技术架构

```text
Next.js 前端
    ↓ HTTP API
FastAPI 后端
    ├── 测评与评分
    ├── Multi-Agent 工作流
    ├── RAG 检索层
    └── DeepSeek LLM 客户端
        ├── BGE-small Embedding
        ├── ChromaDB
        └── CrossEncoder 重排
```

主要技术：

- 前端：Next.js、React、TypeScript、Tailwind CSS、ECharts。
- 后端：Python、FastAPI、Pydantic、SQLAlchemy。
- 业务数据库：当前实际使用 SQLite，文件为 `backend/sage.db`。
- 大模型：通过 OpenAI-compatible API 调用 DeepSeek。
- 向量模型：服务器本地加载 `BAAI/bge-small-zh-v1.5`。
- 重排模型：服务器本地加载 `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`。
- 向量数据库：ChromaDB，持久化目录为 `data/chroma`。

## 3. 一次完整业务流程

### 3.1 动态出题

1. 用户在前端选择 Track、Service 和 Capability。
2. 后端读取服务定义、能力等级、Checklist 和 RAG 检索结果。
3. `question_gen.py` 将这些内容加入 Prompt。
4. DeepSeek 返回结构化 JSON 题目。
5. 前端展示选择题和开放题。

### 3.2 提交与诊断

1. 选择题使用规则进行确定性评分。
2. 开放题根据评分标准得到分数。
3. Diagnosis Agent 针对低分题调用 LLM，识别具体知识盲区。
4. 每个盲区包含 `gap_id`、能力、错误理解、正确理解、严重程度和证据摘录。

### 3.3 学习计划与反思

1. Planning Agent 根据盲区、能力分数、Learning Path 和 RAG 资料生成 5 天计划。
2. 每个任务必须绑定一个或多个 `gap_id`。
3. Reflection Agent 检查计划是否覆盖 critical/major 盲区、内容是否对齐、任务是否可执行。
4. Agent Trace、诊断结果、计划、反思结果和 RAG 来源会保存到测评记录。

编排入口：`backend/app/agents/orchestrator.py`。
Agent 之间通过普通 Python 函数的输入输出连接，不依赖 LangChain：

```text
run_diagnosis() → KnowledgeGap
run_planning(gaps) → LearningPlan
run_reflection(gaps, plan) → critique
```

## 4. 当前 RAG 实现

核心代码：`backend/app/services/rag.py`。

### 4.1 知识来源

- `data/cases/*.json`：真实故障案例、摘要、解决方案和对话。
- `data/taxonomy/learning_path/*.json`：学习主题、资源和实验。
- Service Capability 的 `doc_refs`：官方文档标题、摘要和 URL。

### 4.2 建库过程

1. 统一读取上述数据为 `KnowledgeDocument`。
2. 长文本按约 900 字切分，块之间保留约 120 字重叠。
3. 使用 BGE-small 将文档块转换成向量。
4. 将向量、文本和 metadata 写入 ChromaDB。
5. 使用 corpus signature 判断内容或模型是否变化，必要时自动重建索引。

### 4.3 查询过程

1. 将能力描述或知识盲区组合成查询文本。
2. 使用相同 Embedding 模型生成查询向量。
3. ChromaDB 按余弦相似度召回候选内容。
4. 结合关键词分数进行混合排序：向量约 80%，关键词约 20%。
5. 对候选结果使用 CrossEncoder 重排。
6. 最终返回 Top-K 资料，并把标题、摘要、来源、URL、分数和检索方式注入 Prompt。

当前 RAG 接入两个主要位置：

- `backend/app/services/question_gen.py`：辅助动态出题。
- `backend/app/agents/planning.py`：辅助生成个性化学习计划。

RAG 只负责找资料，DeepSeek 负责基于资料生成题目或计划。

### 4.4 与服务器 `rag_test` Demo 的关系

当前实现和 Demo 使用的是同一套核心思路与模型：BGE-small → ChromaDB → CrossEncoder。
区别是 SAGE 将 Demo 工程化为 `KnowledgeRetriever`，增加了统一数据读取、文本切分、Service/Capability 过滤、索引持久化、自动重建、结果来源记录和业务 Prompt 注入。

重新构建索引：

```bash
cd /home/ubuntu/sage/backend
source /home/ubuntu/rag_test/.venv/bin/activate
python -m app.scripts.reindex_rag
```

## 5. 已完成内容

- [x] Next.js 前端与 FastAPI 后端基本业务闭环。
- [x] 登录、注册、Profile 和角色页面。
- [x] Track/Service/Capability 数据模型。
- [x] 动态生成选择题和开放题。
- [x] 规则评分、能力雷达图和历史测评。
- [x] Diagnosis、Planning、Reflection 多 Agent 流程。
- [x] 后测题目基于前测盲区生成。
- [x] Agent Trace 前端展示与数据库持久化。
- [x] 真实案例、学习路径和官方文档数据集。
- [x] BGE-small、本地 CrossEncoder 和 ChromaDB RAG。
- [x] RAG 接入动态出题和学习计划生成。
- [x] RAG source、score、URL 和 retrieval method 保存。
- [x] 腾讯云 Lighthouse 服务器部署前后端和本地模型。
- [x] Next.js `/api/*` 代理到后端，前端可通过 3000 端口访问。

## 6. 当前已知限制

- 当前业务数据库是 SQLite，不是 PostgreSQL；`DATABASE_URL` 只是预留配置。
- 后端和前端目前是手动后台进程，尚未完全使用 systemd 或 Docker 管理。
- 服务器使用 CPU 推理，模型加载和 LLM 请求耗时较长。
- RAG 知识主要来自项目内置 JSON，尚未实现 PDF/Markdown 上传管理。
- RAG 目前缺少 Recall@K、MRR 等正式评测指标。
- 开放题评分仍需要继续增强语义评分和 rubric 校验。
- Demo 账号、JWT secret 等配置仍是演示级实现，不适合直接作为生产系统。
- 生产环境不应把 LLM API Key、数据库文件、Chroma 索引、模型缓存提交到 Git。

## 7. 推荐后续路线

### P0：优先提升可信度

1. 建立 RAG 评测集，统计 Recall@5、MRR、命中来源准确率。
2. 增加 LLM/RAG 追踪，包括耗时、Prompt、模型、来源和错误信息。
3. 将服务进程改为 systemd 管理，增加自动重启和日志轮转。
4. 删除公开公网 `3000` 的长期依赖，使用 Nginx、HTTPS 和受限访问。

### P1：增强产品完整度

1. 增加 PDF/Markdown/JSON 知识库上传和重新索引。
2. 增加知识库文档列表、删除、版本和索引状态页面。
3. 增强开放题评分：关键点匹配、语义相似度、LLM rubric 结构化评分。
4. 增加跨轮次盲区追踪和学习效果趋势图。
5. 后测完成后根据新盲区自动生成下一轮计划。

### P2：增强工程化和简历亮点

1. 使用 Docker Compose 部署前端、后端和持久化目录。
2. 将 SQLite 迁移到 PostgreSQL，生产环境使用 Alembic 管理迁移。
3. 增加异步任务队列、任务重试、超时和取消机制。
4. 增加单元测试、RAG 回归测试和端到端测试。
5. 视需要再引入 LangGraph/LangChain；当前流程较固定，直接 Python 编排仍然更易解释。

## 8. 简历和面试表达

推荐表述：

> 设计并实现面向技术支持工程师的 AI 能力评估与学习规划系统。基于 FastAPI 和 Next.js 构建多 Agent 工作流，通过 Diagnosis、Planning 和 Reflection Agent 完成答题诊断、知识盲区识别和个性化学习计划生成。将真实故障案例、学习路径和官方文档构建为 ChromaDB 知识库，使用 BGE-small 进行本地向量化，并通过 CrossEncoder 重排检索结果，将 Top-K 资料注入 DeepSeek Prompt，实现基于领域知识的动态出题和学习规划。系统支持 Agent Trace、RAG 来源追踪和腾讯云服务器部署。

## 9. 新对话接手顺序

1. 先阅读本文件。
2. 再阅读 `docs/RAG.md`、`backend/app/services/rag.py` 和 `backend/app/agents/orchestrator.py`。
3. 需要理解业务时阅读 `question_gen.py`、`planning.py`、`assessment.py`。
4. 修改前确认 `.env`、`backend/sage.db`、`data/chroma` 和模型缓存不进入 Git。

