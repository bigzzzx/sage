"""LLM 客户端封装。

DeepSeek 走 OpenAI 兼容协议，后续切换到公司模型时只需改 base_url 和 model。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings


# 调试日志开关：默认开启。设环境变量 LLM_DEBUG=0 关闭
_DEBUG = os.environ.get("LLM_DEBUG", "1") != "0"
_DEBUG_LOG_PATH = Path(__file__).resolve().parents[2] / "llm_debug.log"


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
            "model": self._model,
            "messages": msg_list,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format

        resp = self._client.chat.completions.create(**kwargs)
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
    ) -> tuple[str, int]:
        """同 chat，但同时返回耗时（毫秒）。供 agent trace 使用。"""
        import time
        t0 = time.time()
        content = self.chat(messages, temperature=temperature, response_format=response_format)
        elapsed_ms = int((time.time() - t0) * 1000)
        return content, elapsed_ms

    def chat_traced(
        self,
        messages: Iterable[dict[str, str]],
        *,
        temperature: float = 0.3,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """带耗时统计的 chat。返回 (content, elapsed_ms)。"""
        import time
        t0 = time.time()
        content = self.chat(messages, temperature=temperature, response_format=response_format)
        elapsed_ms = int((time.time() - t0) * 1000)
        return content, elapsed_ms

    def chat_json(
        self,
        messages: Iterable[dict[str, str]],
        *,
        temperature: float = 0.2,
    ) -> str:
        """要求模型返回 JSON 字符串。调用方自行 json.loads。"""
        return self.chat(
            messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )


_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMClient()
    return _singleton
