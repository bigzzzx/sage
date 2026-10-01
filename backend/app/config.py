"""应用配置，统一从环境变量加载。"""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = Field(default="deepseek")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.deepseek.com/v1")
    llm_model: str = Field(default="deepseek-flash")
    auth_secret: str = Field(default="dev-only-change-me")

    # Embedding: openai-compatible, local, or remote_http (/embed).
    embedding_provider: str = Field(default="")
    embedding_api_key: str = Field(default="")
    embedding_base_url: str = Field(default="")
    embedding_model: str = Field(default="")

    # RAG storage
    rag_backend: str = Field(default="chroma")
    rag_chroma_path: str = Field(default="data/chroma")
    rag_collection: str = Field(default="sage_knowledge")
    rag_model_device: str = Field(default="cpu")
    rag_embed_batch_size: int = Field(default=16)
    rag_reranker_enabled: bool = Field(default=False)
    rag_reranker_provider: str = Field(default="local")
    rag_reranker_base_url: str = Field(default="")
    rag_reranker_batch_size: int = Field(default=2)
    rag_reranker_model: str = Field(default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    rag_retrieve_k: int = Field(default=12)
    rag_rerank_k: int = Field(default=5)

    # DB
    database_url: str = Field(default="")

    # App
    app_env: str = Field(default="dev")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    cors_origins: str = Field(default="http://127.0.0.1:3000,http://localhost:3000")
    public_registration: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
