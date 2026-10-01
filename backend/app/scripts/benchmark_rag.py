"""Repeatable local retrieval smoke benchmark; no LLM generation is involved."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

from app.services.rag import get_retriever

QUERIES_PATH = Path(__file__).resolve().parents[3] / "data" / "evals" / "rag_queries.json"


def run(top_k: int = 5, queries_path: Path = QUERIES_PATH) -> dict:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    queries = json.loads(queries_path.read_text(encoding="utf-8"))
    if not isinstance(queries, list) or not queries:
        raise ValueError("query fixture must be a nonempty list")
    init_started = time.perf_counter()
    retriever = get_retriever()
    init_ms = round((time.perf_counter() - init_started) * 1000, 1)
    rows = []
    for item in queries:
        started = time.perf_counter()
        results = retriever.search(query=item["query"], service_id=item["service_id"], limit=top_k)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        ids = [result.document.document_id for result in results]
        expected = item["expected_document_id"]
        rank = next((index for index, doc_id in enumerate(ids, start=1)
                     if doc_id == expected or doc_id.startswith(expected + ":chunk:")), None)
        rows.append({"id": item["id"], "hit": rank is not None, "rank": rank,
                     "elapsed_ms": elapsed_ms, "retrieved_document_ids": ids,
                     "authoritative_source": any(result.document.source_type in
                                                 {"official_doc", "curated_fact"}
                                                 for result in results)})
    latencies = sorted(row["elapsed_ms"] for row in rows)
    p95_index = min(len(latencies) - 1, max(0, math.ceil(0.95 * len(latencies)) - 1))
    return {"backend": "chroma" if retriever._collection is not None else "keyword",
            "init_ms": init_ms,
            "semantic_embeddings": retriever._semantic_embeddings, "query_count": len(rows),
            "top_k": top_k, "hit_at_k": round(sum(row["hit"] for row in rows) / len(rows), 3),
            "hit_at_1": round(sum(row["rank"] == 1 for row in rows) / len(rows), 3),
            "mrr_at_k": round(sum(1 / row["rank"] for row in rows if row["rank"]) / len(rows), 3),
            "authoritative_at_k": round(sum(row["authoritative_source"] for row in rows)
                                        / len(rows), 3),
            "mean_ms": round(statistics.mean(latencies), 1),
            "p95_ms": latencies[p95_index], "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark SAGE local retrieval")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--queries", type=Path, default=QUERIES_PATH)
    parser.add_argument("--min-hit-at-k", type=float, default=1.0)
    args = parser.parse_args()
    report = run(top_k=args.top_k, queries_path=args.queries)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["hit_at_k"] < args.min_hit_at_k:
        raise SystemExit(1)
