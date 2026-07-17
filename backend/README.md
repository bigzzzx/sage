# SAGE Backend

FastAPI 后端服务，负责 AI 调用编排、测评流程、评分、推荐。

## 启动

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env         # 然后编辑 .env 填 DEEPSEEK_API_KEY
uvicorn app.main:app --reload
```

打开 http://localhost:8000/docs 看 API。

## 目录

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置加载
│   ├── api/                 # 路由
│   ├── services/            # 业务逻辑
│   │   └── llm.py           # LLM 客户端
│   ├── schemas/             # Pydantic 数据模型
│   └── scripts/             # 一次性脚本（测试、建模等）
│       └── test_llm.py
├── requirements.txt
└── .env.example
```

## 验证 LLM 是否通

```bash
python -m app.scripts.test_llm
```

期望输出：DeepSeek 返回的一段中文 SE 自我介绍。
