# SAGE 项目当前状态（接续工作请先读这份）

> 最后更新：2026-05-26
> 用途：在新对话窗口快速接续工作。读完这份就能进入工作状态，不需要回看历史对话。

---

## 0. 一分钟快速理解

**项目名**：SAGE — SE Adaptive Growth Engine
**赛道**：PS AI Hackathon 内部效率提升
**核心想法**：把 SE 团队的能力培养，从"凭经验"变成"用数据"。基于真实 case → AI 测评 → 雷达图 → 个性化学习计划 → 后测验证，形成闭环。
**MVP 阶段聚焦**：Big Data 方向，**真实数据用 Glue**（5 个真实 case 建模出来），其他 6 个服务（EMR / Athena / Redshift / Lake Formation / SageMaker / DynamoDB）用模拟 capability 让架构展示完整。

---

## 1. 项目架构

### 三层 Taxonomy（v3 当前架构）

```
Track（职业方向，如 Big Data）
  └── Service（具体服务，如 Glue / EMR）       ← 用户档案雷达图的轴
        └── Capability（能力点，如"Spark 调优"）  ← 单 Service 测评雷达图的轴
              └── Levels: L1 / L2 / L3（熟练度分级）
```

雷达图有两层：
- **单次测评雷达**：以 capability 为轴（在某个 service 内）
- **用户档案雷达**：以 service 为轴（覆盖整个 track）

### 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 前端 | Next.js 16 + React 19 + TS + Tailwind 4 + ECharts | App Router 模式 |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 | 启用 `--reload` |
| 数据库 | SQLite（`backend/sage.db`） | Hackathon 阶段零运维 |
| LLM | 阿里云百炼 qwen-plus（OpenAI 兼容协议） | 国内网络稳定，免费额度够用 |
| Embedding | （暂未启用） | 后续接 BGE 或通义 v3 |
| Python 环境 | conda env `sage`（Python 3.12.13）| 在 `C:\Users\0856\.conda\envs\sage\` |

### 目录结构

```
AI Hackathon/
├── 项目概述.md                # 最初的项目提案
├── README.md                   # 对外门面（已更新）
├── docs/
│   ├── PROJECT_STATUS.md       # 本文件 — 接续工作必读
│   └── PROMPTS.md              # 4 个核心 prompt 的设计意图
├── backend/
│   ├── .env / .env.example     # LLM_API_KEY 等
│   ├── requirements.txt
│   ├── sage.db                 # SQLite 数据库（gitignored）
│   ├── llm_debug.log           # 所有 prompt + 回复日志（gitignored）
│   ├── dump_last_assessment.py # 调试用：dump 最近一次测评内容
│   └── app/
│       ├── main.py             # FastAPI 入口 + lifespan init_db
│       ├── config.py           # pydantic-settings 加载 .env
│       ├── db.py               # SQLAlchemy engine + SessionLocal
│       ├── models.py           # ORM: Assessment 表
│       ├── api/
│       │   └── assessment.py   # 所有 /api/assessment/* 路由
│       ├── schemas/
│       │   └── assessment.py   # Pydantic 请求/响应模型
│       ├── services/
│       │   ├── llm.py          # 百炼客户端封装 + 调试日志
│       │   ├── taxonomy.py     # 加载 tracks.json + services/*.json
│       │   ├── question_gen.py # 动态出题（含会话缓存 _session_store）
│       │   └── assessment.py   # 测评编排 + 持久化 + 学习计划 + 业务规则
│       └── scripts/
│           └── test_llm.py     # 简单 LLM 连通性测试
├── frontend/
│   ├── package.json
│   └── src/
│       ├── lib/
│       │   └── api.ts          # 后端调用封装（带 PendingPostTestError）
│       ├── components/
│       │   ├── RadarChart.tsx       # capability 级雷达
│       │   ├── TrackRadarChart.tsx  # service 级雷达
│       │   └── HeatmapChart.tsx     # 团队热力图
│       └── app/
│           ├── page.tsx             # 首页
│           ├── assessment/page.tsx  # 测评配置 + 答题（含 pending check）
│           ├── result/page.tsx      # 测评结果 + 学习计划 + 完整回顾
│           ├── post-test/page.tsx   # 后测页
│           ├── profile/page.tsx     # 用户能力档案（Track 雷达）
│           └── dashboard/page.tsx   # 经理团队看板
├── data/
│   ├── cases/                  # Glue 真实 case（脱敏后的 JSON）
│   │   ├── README.md           # case 整理规范
│   │   ├── _template.json
│   │   └── glue-001 ~ glue-005.json
│   ├── taxonomy/
│   │   ├── tracks.json         # Track + Service 索引
│   │   ├── services/
│   │   │   ├── glue.json       # 真实建模的 7 capabilities（is_real: true）
│   │   │   ├── emr.json        # 模拟 6 capabilities
│   │   │   ├── athena.json     # 模拟
│   │   │   ├── redshift.json   # 模拟
│   │   │   ├── lake_formation.json
│   │   │   ├── sagemaker.json
│   │   │   └── dynamodb.json
│   │   └── glue_taxonomy.json  # 旧版（已被 services/glue.json 取代，可删）
│   ├── questions/              # 离线兜底题目（已基本不用）
│   └── scores/                 # e2e 测试输出
└── scripts/                    # 离线脚本（开发期用过的）
    ├── build_taxonomy.py       # 离线建模（一次性）
    ├── generate_questions.py   # 离线出题（已被 question_gen.py 替代）
    ├── score_answers.py        # 离线评分（已被 service 内嵌）
    └── e2e_test.py             # 端到端串测
```

---

## 2. 已完成功能 ✅

### AI 核心链路（全部跑通）

- [x] LLM 调用：百炼 qwen-plus，OpenAI 兼容协议
- [x] 能力维度建模：Glue 用 5 个真实 case 离线建模出 7 capabilities
- [x] 动态出题：在线 LLM 生成，可指定 service + capability + 难度
- [x] 选择题自动判分（A/B/C/D 比对）
- [x] 开放题 AI 多维评分（5 个维度：准确性/完整性/诊断思路/深度/实操性）
- [x] 单 capability 维度收敛（单题样本极端值往中位 2.5 收敛 50%）
- [x] 学习计划：1 周聚焦、5 种任务类型、带超链接、每天 60~120min
- [x] 后测：根据前测薄弱 capability 定向出题
- [x] 前后对比：后测结果含 prev_capability_radar 字段

### 业务规则

- [x] 同 service 内未完成后测时，**禁止**开新前测（API 返回 409 + `PENDING_POST_TEST`）
- [x] 跨 service 允许并行学习
- [x] 测评页选完 service 立即查询 pending，给醒目 UI 提示
- [x] 选项字母用下标算（修复了之前的"全选中"bug）

### 持久化

- [x] SQLite + SQLAlchemy ORM
- [x] `Assessment` 表保存：题目快照、答案、评分、雷达、学习计划
- [x] 用户级 Track 雷达 API（取每个 service 最近一次测评聚合）
- [x] 测评历史 API

### 前端页面

- [x] `/`：首页（Hero + Stats + Features + 工作流）
- [x] `/assessment`：Track→Service→Capability 三步选择，含 pending 提示
- [x] `/result`：单 service 雷达 + 学习计划（卡片式带超链接）+ 完整回顾
- [x] `/post-test?prev=xxx`：后测专属页
- [x] `/profile`：用户能力档案（Track 级雷达 + Service 详情列表）
- [x] `/dashboard`：经理看板（5 mock 成员 + 我，热力图 + 培训建议）

### 开发体验

- [x] LLM 调试日志（`backend/llm_debug.log`，含完整 prompt + 回复，可关）
- [x] `dump_last_assessment.py`：命令行查看最近一次测评的完整内容

---

## 3. 关键设计决策（避免新对话重新讨论）

| 决策 | 为什么 |
|---|---|
| **三层 Taxonomy（Track/Service/Capability）** | 用户问"为什么只有 Glue 维度"后改的。让雷达图能展示职业全貌，新增服务只需加一个 JSON 文件 |
| **Glue 真实 + 其他模拟** | 用户拍板的方案 B：架构按完整设计来，演示效果有冲击力，不需要补几十个 case |
| **SQLite 而非 PostgreSQL** | Hackathon 时间紧，SQLite 文件库零运维，足够 demo |
| **百炼 qwen-plus** | 国内 AWS 没有 Bedrock，百炼免费额度够用，OpenAI 兼容协议好接 |
| **单题维度收敛 50%** | 解决"单题答错→该维度直接 0/5"的极端化问题。算法：`raw * 0.5 + 2.5 * 0.5` |
| **同 service 内拦截重复前测** | 强制学习闭环。跨 service 不拦截（允许并行学不同服务） |
| **session_id 内存缓存而非入库** | 出题→提交是连续操作，session 短命；用 dict 简单高效 |
| **后测 session_id 拼接 prev_id**：`"{session}:{prev_id}"` | 避免再加一个字段，post-test/submit 直接拆分 |

---

## 4. 当前主要问题（用户反馈过的，已修复）

- ❌ ~~选择题选一个全亮~~ → 已用 `String.fromCharCode(65 + idx)` 修复
- ❌ ~~首页太空~~ → 已加 stats / features / workflow
- ❌ ~~选择题写得像排查类~~ → prompt 加了强制规则 + 反例
- ❌ ~~只有 Glue 维度~~ → 重构成三层架构
- ❌ ~~学习计划资源没链接、周期太长~~ → 改成 1 周、带 URL、5 种任务类型

## 5. 已知问题 / TODO

- [ ] **首页文案**：可以更打动人；如果做演示要再润色
- [ ] **EMR/Athena 等模拟 service**：capability 是合理的，但用户实际答题质量未充分测试
- [ ] **学习资源链接**：依赖 LLM 给的 URL，可能有死链；演示前最好抽查几条
- [ ] **没有用户系统**：所有操作 user_id 都写死 `demo_user`
- [ ] **经理看板的成员是 mock**：`MOCK_MEMBERS` 数组，不接入真实多用户数据
- [ ] **没有真实的 KB 向量检索**：学习资源完全靠 LLM 生成，没有 embedding 检索的"项目原始设想"
- [ ] **数据库 schema 变更需要手动删 db**：没接 alembic 之类迁移工具

---

## 6. 常用命令

### 启动

```powershell
# 后端（在 backend/ 目录）
& "C:\Users\0856\.conda\envs\sage\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端（在 frontend/ 目录）
cmd /c "npm run dev"
# 注意：直接 npm run dev 在某些 PowerShell 环境下 stdout 行为异常，用 cmd /c 包一层最稳
```

访问：
- 前端：http://localhost:3000
- 后端 docs：http://localhost:8000/docs

### 调试

```powershell
# 看最近一次测评的完整内容（题目+答案+评分+反馈）
& "C:\Users\0856\.conda\envs\sage\python.exe" backend\dump_last_assessment.py

# 看 LLM 完整 prompt + 回复
type backend\llm_debug.log

# 关 LLM 日志
$env:LLM_DEBUG = "0"
```

### 重置数据

```powershell
# 清空 DB（会丢失所有测评历史）
Remove-Item backend\sage.db
# 重启后端会自动建表
```

---

## 7. 关键 API 速查

```
# 元数据
GET  /api/assessment/taxonomy                   # 完整 Track/Service/Capability 树
GET  /api/assessment/tracks                     # 仅 Track 索引
GET  /api/assessment/services/{service_id}      # 单 service 详情

# 测评核心
POST /api/assessment/generate                   # 动态出题（前测，会拦截 PENDING）
POST /api/assessment/submit                     # 提交前测答案
POST /api/assessment/post-test/generate         # 后测出题（自动选薄弱 capability）
POST /api/assessment/post-test/submit           # 提交后测，返回前后对比

# 用户视图
GET  /api/assessment/users/{user_id}/track-radar?track_id=big_data
GET  /api/assessment/users/{user_id}/pending-post-test?service_id=glue
GET  /api/assessment/history/{user_id}
```

---

## 8. 演示故事（5 分钟脚本）

```
1. 首页（30s）：讲 SAGE 是什么，把 SE 培养从凭经验变成用数据
2. 测评（90s）：选 Big Data → Glue → 选几个 capability → AI 出题（15-30s）→ 答几道
3. 提交评分（60s）：AI 多维度评分（30-60s 等待）
4. 结果页（90s）：
   - 雷达图 + 各 capability 得分
   - 个性化 1 周学习计划（点开几个超链接演示）
   - 完整回顾（选择题对错 + 开放题 5 维度评分）
5. 我的能力档案（30s）：Big Data Track 雷达，Glue 已亮，其他服务待测
6. 经理看板（30s）：团队热力图 + 最薄弱服务建议
```

**演示前必做**：
- 先跑一次完整流程，确认百炼 API 工作正常
- 删库重建：演示用 demo_user 账号最好是干净的（避免 pending 拦截）
- 备一个录屏，万一现场网络不稳

---

## 9. 给新对话窗口的指引

如果你是新窗口的 Kiro，**第一件事请做**：

1. 读这份 `docs/PROJECT_STATUS.md`
2. 读 `docs/PROMPTS.md` 了解 prompt 设计意图
3. 浏览 `项目概述.md` 了解最初提案
4. **不需要重新读** 5 个 case 文件（除非用户要新增/修改 case）
5. **不需要重新读** 其他 6 个模拟 service 的 JSON（除非要改）

环境就绪后，直接根据用户当前要求继续工作。

如果用户没有明确指令，可以问：
- 是要继续完善某个功能？
- 还是要打磨演示？
- 或者添加新数据/case？


---

## 10. 切换对话窗口前的最终交接（2026-05-26）

> 这一节是上一个对话窗口结束前的总结，给下一个窗口的 Kiro 看。

### 当前最后跑通的状态

- ✅ 后端 + 前端都在跑（PowerShell 进程 ID 不重要，重启即可）
- ✅ 三层 taxonomy 已重构完成，7 个 service JSON 都在
- ✅ 学习计划 prompt 改成 1 周 + 多任务类型 + 带 URL
- ✅ 业务规则：同 service 未完成后测时拦截重复前测
- ✅ 选择题 A/B/C/D 标识 bug 已修
- ✅ 雷达图单题样本极端值收敛已修

### 演示前必做清单（按优先级）

#### 🔴 P0 — 不做就开天窗

1. **环境冒烟测**：删 sage.db → 重启前后端 → 跑一次完整流程（前测 → 学计划 → 后测 → 看雷达对比） → 看 `/profile` 雷达图亮起 → 看 `/dashboard` 团队看板正常
2. **百炼 API 余额检查**：登 [百炼控制台](https://bailian.console.aliyun.com) 看 qwen-plus 免费额度还剩多少 token；演示一次 ~ 8000 token，留够余量
3. **录一段备用 demo 视频**：万一现场网络/API 抽风，直接放视频

#### 🟡 P1 — 强烈建议做

4. **学习计划 URL 抽查**：跑一次测评后看学习计划里的 URL，挑 3~5 个点开，确认不是死链；如果 LLM 给的链接质量不行，调 `_PLAN_PROMPT` 的"白名单域名"段
5. **演示账号准备干净**：删 `sage.db` 让 `demo_user` 是全新的，避免被 pending 拦截卡住
6. **选 demo 维度**：测评时选 1~2 个 Glue capability（不是全部），让 AI 出 4 选 + 2 开放，时长可控（每道开放题评分 ~10s，3 道开放就要 30s+）

#### 🟢 P2 — 时间充裕再做

7. **首页文案润色**：现在文案还行，但"一句话讲清价值"可以再打磨
8. **加一个 "EMR" 真实 case** 让演示故事更厚（"看，这是 EMR 真实数据驱动的能力图"）
9. **经理看板 mock 成员名**：现在 Alice/Bob 太通用，可以换成 SE-001、SE-002 或更"业务感"的名字

### 当前已知的小毛病（不致命，但演示要避开）

- ⚠️ **后端 reload 偶尔挂**：保存 .py 时 watchfiles 报 KeyboardInterrupt，但通常服务还在跑。如果发现 8000 端口不响应，就重启
- ⚠️ **前端 `npm run dev` 直接调可能 stdout 阻塞**：用 `cmd /c "npm run dev"` 包一层
- ⚠️ **学习计划 LLM 偶尔返回非合法 JSON**：会触发兜底 `plan_name: "学习计划生成失败"`。重试一次基本能恢复
- ⚠️ **PowerShell 控制台显示中文乱码**：是终端编码问题，HTTP 响应实际是正确 UTF-8

### 用户的工作风格（给新 Kiro 参考）

- 直接、不绕弯，不喜欢冗长的客套
- 喜欢"先问后做"重大决策（比如"按 A 还是 B 方案"），不喜欢自作主张大改
- 喜欢看到具体的可视化效果（截图反馈很多）
- 重视产品体验细节（曾反馈选择题歧义、首页紧凑、学习计划粗糙等）
- 时间紧，倾向于"先动起来再调"
- 中文沟通

### 用户提供的 case 数据现状

- **5 个 Glue case 已脱敏存好**（`data/cases/glue-001 ~ glue-005.json`）
- 用户表示：会逐步补真实 case，目前其他服务用模拟数据先撑场面（用户拍板的方案 B）
- 如果用户后续给新 case，按 `data/cases/README.md` 规范整理

### 下一步推荐方向（如果用户没有明确指令）

按"对演示效果提升 / 实现成本"权衡排序：

1. **演示打磨**（P0 那几条）— 最高 ROI
2. **加 1~2 个 EMR 或 Athena 的真实 case** — 让"big data 全方位"故事更扎实
3. **首页 / 学习计划文案再润色** — 影响第一印象
4. **后测做完后给一个"恭喜你提升了 X 分"的成就感页面** — 闭环故事更动人
5. （Hackathon 之外）多用户系统、向量检索、Docker 化

---

✅ 这份文档 + 代码本身 = 完整的项目状态。可以放心切换窗口。
