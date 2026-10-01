"""LLM 客户端封装。

DeepSeek 走 OpenAI 兼容协议，后续切换到公司模型时只需改 base_url 和 model。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import httpx
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings


# Raw prompts may contain personal answers; logging is opt-in and disabled in production.
_DEBUG = os.environ.get("LLM_DEBUG", "0") == "1" and get_settings().app_env.lower() != "production"
_DEBUG_LOG_PATH = Path(__file__).resolve().parents[2] / "llm_debug.log"
_usage_sink: ContextVar[list[dict] | None] = ContextVar("sage_llm_usage_sink", default=None)


@contextmanager
def capture_llm_usage():
    """Collect per-attempt metadata without retaining prompts or model replies."""
    records: list[dict] = []
    token = _usage_sink.set(records)
    try:
        yield records
    finally:
        _usage_sink.reset(token)


def _debug_log(role: str, content: str) -> None:
    """把 prompt 和回复追加到 backend/llm_debug.log。"""
    if not _DEBUG:
        return
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as fp:
            ts = datetime.now().isoformat(timespec="seconds")
            fp.write(f"\n========== {ts} [{role}] ==========\n")
            fp.write(content)
            fp.write("\n")
    except Exception:
        pass


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY 未配置，请在 backend/.env 中填入 DeepSeek API key"
            )
        self._client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            http_client=httpx.Client(trust_env=False),
        )
        self._model = settings.llm_model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def chat(
        self,
        messages: Iterable[dict[str, str]],
        *,
        temperature: float = 0.3,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        """普通对话调用，返回纯文本。"""
        msg_list = list(messages)

        # 调试日志：记录发出的 prompt
        if _DEBUG:
            try:
                _debug_log("REQUEST", json.dumps(msg_list, ensure_ascii=False, indent=2))
            except Exception:
                pass

        kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": msg_list,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format

        sink = _usage_sink.get()
        started = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception:
            if sink is not None:
                sink.append({"model": kwargs["model"], "elapsed_ms": round((time.perf_counter() - started) * 1000),
                             "prompt_tokens": None, "completion_tokens": None, "status": "failed"})
            raise
        if sink is not None:
            usage = getattr(resp, "usage", None)
            sink.append({"model": kwargs["model"], "elapsed_ms": round((time.perf_counter() - started) * 1000),
                         "prompt_tokens": getattr(usage, "prompt_tokens", None),
                         "completion_tokens": getattr(usage, "completion_tokens", None), "status": "ok"})
        content = resp.choices[0].message.content or ""

        # 调试日志：记录模型回复
        if _DEBUG:
            _debug_log("RESPONSE", content)

        return content

    def chat_traced(
        self,
        messages: Iterable[dict[str, str]],
        *,
        temperature: float = 0.3,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> tuple[str, int]:
        """带耗时统计的 chat。返回 (content, elapsed_ms)。"""
        import time
        t0 = time.time()
        content = self.chat(messages, temperature=temperature, response_format=response_format, model=model)
        elapsed_ms = int((time.time() - t0) * 1000)
        return content, elapsed_ms

    def chat_json(
        self,
        messages: Iterable[dict[str, str]],
        *,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str:
        """要求模型返回 JSON 字符串。调用方自行 json.loads。"""
        return self.chat(
            messages,
            temperature=temperature,
            response_format={"type": "json_object"},
            model=model,
        )

    def list_models(self) -> list[str]:
        """通过 OpenAI 兼容的 /models 接口枚举当前凭据可用模型。"""
        response = self._client.models.list(timeout=15.0)
        return sorted({
            model_id for item in response.data
            if (model_id := str(getattr(item, "id", "")).strip()) and len(model_id) <= 128
        })


_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMClient()
    return _singleton


def get_available_models() -> dict[str, Any]:
    """Return safe model IDs; when discovery is unsupported, expose only the configured default."""
    settings = get_settings()
    default_model = settings.llm_model.strip()
    if not settings.llm_api_key:
        return {
            "configured": False,
            "default_model": default_model,
            "models": [],
            "discovery_available": False,
            "warning": "服务端尚未配置模型密钥",
        }

    try:
        discovered = get_llm().list_models()
    except Exception:
        discovered = []

    discovery_available = bool(discovered)
    models = sorted({model_id for model_id in discovered if model_id} | ({default_model} if default_model else set()))
    return {
        "configured": True,
        "default_model": default_model,
        "models": models,
        "discovery_available": discovery_available,
        "warning": None if discovery_available else "无法自动读取模型列表，当前仅显示服务端默认模型",
    }


def resolve_generation_model(model_id: str | None) -> str:
    """Validate a UI-selected model against live discovery (or the configured fallback)."""
    settings = get_settings()
    default_model = settings.llm_model.strip()
    if not model_id:
        return default_model
    if len(model_id) > 128:
        raise ValueError("所选模型无效，请刷新模型列表后重试")
    available = get_available_models()
    if model_id not in available["models"]:
        raise ValueError("所选模型当前不可用，请刷新模型列表后重试")
    return model_id
