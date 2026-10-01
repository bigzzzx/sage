"""Curated public AWS Glue facts shared by generation, diagnosis and planning."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FACTS_PATH = Path(__file__).resolve().parents[3] / "data" / "evals" / "glue_public_facts.json"


@lru_cache(maxsize=1)
def load_glue_facts() -> list[dict]:
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(facts, list) or not facts:
        raise ValueError("Glue 公开考点为空")
    return facts


def format_glue_facts() -> str:
    return "\n".join(
        f"- [{item['level']}][{item['id']}] {item['fact']} 官方依据：{item['source']}"
        for item in load_glue_facts()
    )


def glue_fact_sources() -> list[dict]:
    """Expose only explicit official references, never model-invented URLs."""
    return [
        {"document_id": f"glue-fact:{item['id']}", "title": item["id"],
         "source_type": "official_doc", "url": item["source"],
         "excerpt": item["fact"], "score": 1.0,
         "capability_id": "", "retrieval_method": "curated"}
        for item in load_glue_facts()
    ]
