"""Print the current RAG corpus coverage without opening or rebuilding Chroma."""
from __future__ import annotations

import json

from app.services.rag import knowledge_coverage


if __name__ == "__main__":
    print(json.dumps(knowledge_coverage(), ensure_ascii=False, indent=2))
