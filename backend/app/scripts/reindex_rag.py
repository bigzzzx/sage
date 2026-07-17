"""Build or refresh the persistent ChromaDB knowledge index."""
from __future__ import annotations

from app.services.rag import get_retriever


def main() -> None:
    result = get_retriever().rebuild_index(force=True)
    print(f"RAG index rebuilt: backend={result['backend']}, documents={result['indexed']}")


if __name__ == "__main__":
    main()
