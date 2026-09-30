"""Compare SAGE's BM25 with remote dense recall and reranking.

This opt-in benchmark sends the complete local knowledge corpus (including
internal case records) through localhost SSH forwards. Run only with the data
owner's authorization. It neither writes remote files nor changes the live RAG.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path

import httpx

from app.scripts.benchmark_public_remote_rag import _embed, _loopback, _rerank
from app.services.rag import (_bm25_rank, _diversify, _expanded_query,
                              _fuse_rankings, load_knowledge_documents)


EVAL_DIR = Path(__file__).resolve().parents[3] / "data" / "evals"
QUERY_FILES = (EVAL_DIR / "rag_queries.json", EVAL_DIR / "rag_queries_diagnostic.json")


def _rank(results: list, expected: str) -> int | None:
    return next((rank for rank, result in enumerate(results, 1)
                 if result.document.document_id == expected
                 or result.document.document_id.startswith(expected + ":chunk:")), None)


def run(embed_url: str = "http://127.0.0.1:18081/embed",
        rerank_url: str = "http://127.0.0.1:18082/rerank") -> dict:
    embed_url, rerank_url = _loopback(embed_url), _loopback(rerank_url)
    documents = list(load_knowledge_documents())
    questions = [row for path in QUERY_FILES for row in json.loads(path.read_text(encoding="utf-8"))]
    rows = {arm: [] for arm in ("bm25", "dense", "hybrid", "hybrid_rerank")}
    with httpx.Client(trust_env=False, timeout=120) as client:
        started = time.perf_counter()
        vectors = []
        for start in range(0, len(documents), 16):
            vectors.extend(_embed(client, embed_url,
                                  [doc.content for doc in documents[start:start + 16]]))
        embedding_ms = round((time.perf_counter() - started) * 1000, 1)
        dimensions = len(vectors[0])
        for item in questions:
            query, service_id = item["query"], item["service_id"]
            pairs = [(doc, vector) for doc, vector in zip(documents, vectors)
                     if doc.service_id == service_id]
            filtered = [doc for doc, _ in pairs]
            started = time.perf_counter()
            lexical = [[doc for doc, _ in _bm25_rank(query, filtered)[:32]]]
            expanded = _expanded_query(query)
            if expanded != query:
                lexical.append([doc for doc, _ in _bm25_rank(expanded, filtered)[:32]])
            bm25 = _diversify(_fuse_rankings(lexical, 64, "bm25_rrf"), 5)
            bm25_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            query_vector = _embed(client, embed_url, [query])[0]
            dense_docs = [doc for doc, vector in sorted(
                pairs, key=lambda pair: -sum(a * b for a, b in zip(query_vector, pair[1])))[:32]]
            dense = _diversify(_fuse_rankings([dense_docs], 32, "dense"), 5)
            dense_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            merged = _fuse_rankings(lexical + [dense_docs], 96, "hybrid_rrf")
            hybrid = _diversify(merged, 5)
            hybrid_ms = bm25_ms + dense_ms + (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            pool = merged[:12]
            scores = _rerank(client, rerank_url, query,
                             [result.document.content for result in pool])
            reranked = _diversify([result for result, _ in sorted(
                zip(pool, scores), key=lambda pair: -pair[1])], 5)
            rerank_ms = hybrid_ms + (time.perf_counter() - started) * 1000

            for arm, results, elapsed in (("bm25", bm25, bm25_ms),
                                          ("dense", dense, dense_ms),
                                          ("hybrid", hybrid, hybrid_ms),
                                          ("hybrid_rerank", reranked, rerank_ms)):
                rows[arm].append({"id": item["id"], "rank": _rank(results, item["expected_document_id"]),
                                  "ms": round(elapsed, 1),
                                  "top5": [result.document.document_id for result in results]})

    summary = {}
    for arm, arm_rows in rows.items():
        latencies = sorted(row["ms"] for row in arm_rows)
        summary[arm] = {
            "hit_at_1": round(sum(row["rank"] == 1 for row in arm_rows) / len(arm_rows), 3),
            "hit_at_5": round(sum(row["rank"] is not None for row in arm_rows) / len(arm_rows), 3),
            "mrr_at_5": round(sum(1 / row["rank"] for row in arm_rows if row["rank"]) / len(arm_rows), 3),
            "mean_ms": round(statistics.mean(latencies), 1),
            "p95_ms": latencies[min(len(latencies) - 1, math.ceil(.95 * len(latencies)) - 1)],
            "misses": [row["id"] for row in arm_rows if row["rank"] is None],
        }
    return {"scope": "full SAGE corpus including internal cases and learning paths",
            "corpus_chunks": len(documents), "queries": len(questions),
            "embedding_dimensions": dimensions, "corpus_embedding_ms": embedding_ms,
            "arms": summary, "rows": rows}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
