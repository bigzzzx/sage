"""SAGE Backend 入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 建表；管理员必须由部署者显式创建，不自动生成凭据。
    init_db()
    from app.services.tasks import mark_interrupted_tasks
    mark_interrupted_tasks()
    yield


app = FastAPI(
    title="SAGE API",
    description="SE Adaptive Growth Engine - Backend",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.api.assessment import router as assessment_router
from app.api.auth import router as auth_router
from app.api.auth import get_current_user
from app.api.practice import router as practice_router
from app.api.tickets import router as tickets_router
from app.api.learning import router as learning_router
from app.api.admin import router as admin_router
from app.api.knowledge import router as knowledge_router
from app.api.feedback import router as feedback_router
from app.api.assignments import router as assignments_router

app.include_router(assessment_router)
app.include_router(auth_router)
app.include_router(practice_router)
app.include_router(tickets_router)
app.include_router(learning_router)
app.include_router(admin_router)
app.include_router(knowledge_router)
app.include_router(feedback_router)
app.include_router(assignments_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "SAGE API",
        "version": app.version,
        "env": settings.app_env,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/llm/ping")
def llm_ping(current: dict = Depends(get_current_user)) -> dict[str, str]:
    """探测 LLM 是否能正常调用。仅用于开发期自检。"""
    if settings.app_env.lower() == "production" or current["r"] != "manager":
        raise HTTPException(403, "仅开发环境管理员可调用模型探针")
    if not settings.llm_api_key:
        raise HTTPException(503, "LLM_API_KEY 未配置")
    from app.services.llm import get_llm

    try:
        reply = get_llm().chat(
            [
                {"role": "system", "content": "你是 SAGE 系统的健康探针。"},
                {"role": "user", "content": "用一句话回答：你好。"},
            ],
            temperature=0.0,
        )
    except Exception as exc:
        raise HTTPException(503, "模型服务暂不可用") from exc
    return {"reply": reply}


@app.get("/api/llm/status")
def llm_status(current: dict = Depends(get_current_user)) -> dict[str, bool]:
    """Configuration only; does not claim provider connectivity."""
    return {"configured": bool(settings.llm_api_key)}


@app.get("/api/llm/models")
def llm_models(current: dict = Depends(get_current_user)) -> dict:
    """Discover available model IDs without exposing credentials or provider errors."""
    from app.services.llm import get_available_models

    return get_available_models()
