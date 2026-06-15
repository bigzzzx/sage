"""SAGE Backend 入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 建表 + 预置用户
    init_db()
    from app.api.auth import ensure_preset_users
    ensure_preset_users()
    yield


app = FastAPI(
    title="SAGE API",
    description="SE Adaptive Growth Engine - Backend",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.api.assessment import router as assessment_router
from app.api.auth import router as auth_router

app.include_router(assessment_router)
app.include_router(auth_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "SAGE API",
        "version": "0.1.0",
        "env": settings.app_env,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/llm/ping")
def llm_ping() -> dict[str, str]:
    """探测 LLM 是否能正常调用。仅用于开发期自检。"""
    from app.services.llm import get_llm

    reply = get_llm().chat(
        [
            {"role": "system", "content": "你是 SAGE 系统的健康探针。"},
            {"role": "user", "content": "用一句话回答：你好。"},
        ],
        temperature=0.0,
    )
    return {"reply": reply}
