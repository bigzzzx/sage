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
    llm_model: str = Field(default="deepseek-chat")

    # Embedding（暂未启用）
    embedding_provider: str = Field(default="")
    embedding_api_key: str = Field(default="")
    embedding_base_url: str = Field(default="")
    embedding_model: str = Field(default="")

    # DB
    database_url: str = Field(default="")

    # App
    app_env: str = Field(default="dev")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
