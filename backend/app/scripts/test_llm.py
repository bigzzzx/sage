"""验证 LLM 调用是否打通。

用法：
    cd backend
    python -m app.scripts.test_llm
"""
from __future__ import annotations

from app.services.llm import get_llm


def main() -> None:
    print("==> 调用 DeepSeek，请稍候...")
    reply = get_llm().chat(
        [
            {
                "role": "system",
                "content": "你是一名 AWS Glue 方向的资深 SE。回答务必简洁。",
            },
            {
                "role": "user",
                "content": "用 2~3 句话介绍下 AWS Glue 是什么，以及它解决什么问题。",
            },
        ],
        temperature=0.3,
    )
    print("\n==> 模型回复：\n")
    print(reply)
    print("\n==> 测试通过 ✅")


if __name__ == "__main__":
    main()
