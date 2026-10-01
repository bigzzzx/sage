"""Compare retrieval arms using only public AWS text over localhost SSH tunnels.

Only curated PUBLIC Glue facts, public AWS documentation excerpts and their
public assessment questions leave this machine. Case files, learning paths,
user data and the project's persistent vector index are never read or sent.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.services.glue_sources import load_glue_facts
from app.services.rag import (KnowledgeDocument, _bm25_rank, _chunk_document,
                              _diversify, _expanded_query, _fuse_rankings,
                              _official_snapshot)
from app.services.taxonomy import get_service


def _public_documents() -> list[KnowledgeDocument]:
    facts = load_glue_facts()
    documents = [KnowledgeDocument(f"fact:glue:{fact['id']}", fact["id"],
                                   "curated_fact", fact["fact"], "glue", url=fact["source"])
                 for fact in facts]
    seen = set()
    for capability in get_service("glue").get("capabilities", []):
        for ref in capability.get("doc_refs") or []:
            snapshot = _official_snapshot(ref.get("url", ""))
            if not snapshot or ref["url"] in seen:
                continue
            seen.add(ref["url"])
            # Send ONLY the captured official page body, not taxonomy summaries.
            raw = KnowledgeDocument("publicdoc:" + hashlib.sha256(ref["url"].encode()).hexdigest()[:14],
                                    ref["title"], "official_doc", snapshot["text"], "glue",
                                    capability.get("id", ""), snapshot["resolved_url"])
            documents.extend(_chunk_document(raw))
    if any(doc.source_type not in {"curated_fact", "official_doc"} for doc in documents):
        raise ValueError("Non-public source found in evaluation corpus")
    return documents


def _loopback(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Model APIs must be reached through localhost SSH tunnels")
    return url


def _embed(client: httpx.Client, url: str, texts: list[str]) -> list[list[float]]:
    response = client.post(url, json={"inputs": texts, "normalize": True})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("Unexpected embedding batch size")
    return data


def _rerank(client: httpx.Client, url: str, query: str, texts: list[str]) -> list[float]:
    scores = [0.0] * len(texts)
    # This shared service has a small memory limit; large rerank batches restart it.
    for start in range(0, len(texts), 2):
        batch = texts[start:start + 2]
        response = client.post(url, json={"query": query, "texts": batch})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or {x.get("index") for x in data} != set(range(len(batch))):
            raise ValueError("Unexpected reranker indices")
        for item in data:
            scores[start + item["index"]] = float(item["score"])
    return scores


def _rank(results: list, expected: str) -> int | None:
    return next((rank for rank, item in enumerate(results, start=1)
                 if item.document.document_id == expected), None)


def run(embed_url: str = "http://127.0.0.1:18081/embed",
        rerank_url: str = "http://127.0.0.1:18082/rerank") -> dict:
    embed_url, rerank_url = _loopback(embed_url), _loopback(rerank_url)
    documents = _public_documents()
    questions = [(fact["id"], fact["question"]) for fact in load_glue_facts()]
    arms = {name: [] for name in ("bm25", "dense", "hybrid", "hybrid_rerank")}
    with httpx.Client(trust_env=False, timeout=120) as client:
        started = time.perf_counter()
        vectors = []
        for start in range(0, len(documents), 16):
            vectors.extend(_embed(client, embed_url,
                                  [doc.content for doc in documents[start:start + 16]]))
        corpus_embedding_ms = round((time.perf_counter() - started) * 1000, 1)
        dimensions = len(vectors[0])
        if any(len(vector) != dimensions for vector in vectors):
            raise ValueError("Inconsistent embedding dimensions")
        for fact_id, query in questions:
            expected = f"fact:glue:{fact_id}"
            started = time.perf_counter()
            rankings = [[doc for doc, _ in _bm25_rank(query, documents)[:32]]]
            expanded = _expanded_query(query)
            if expanded != query:
                rankings.append([doc for doc, _ in _bm25_rank(expanded, documents)[:32]])
            bm25 = _diversify(_fuse_rankings(rankings, 64, "bm25_rrf"), 5)
            bm25_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            qvec = _embed(client, embed_url, [query])[0]
            dense_docs = [doc for doc, vector in sorted(zip(documents, vectors),
                          key=lambda pair: -sum(a * b for a, b in zip(qvec, pair[1])))[:32]]
            dense = _diversify(_fuse_rankings([dense_docs], 32, "dense"), 5)
            dense_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            merged = _fuse_rankings(rankings + [dense_docs], 96, "hybrid_rrf")
            hybrid = _diversify(merged, 5)
            hybrid_ms = bm25_ms + dense_ms + (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            rerank_pool = merged[:16]
            scores = _rerank(client, rerank_url, query,
                             [item.document.content for item in rerank_pool])
            ordered = [item for item, score in sorted(zip(rerank_pool, scores),
                                                      key=lambda pair: -pair[1])]
            reranked = _diversify(ordered, 5)
            rerank_ms = hybrid_ms + (time.perf_counter() - started) * 1000
            for arm, results, elapsed in (("bm25", bm25, bm25_ms), ("dense", dense, dense_ms),
                                          ("hybrid", hybrid, hybrid_ms),
                                          ("hybrid_rerank", reranked, rerank_ms)):
                arms[arm].append({"fact_id": fact_id, "rank": _rank(results, expected),
                                  "ms": round(elapsed, 1)})
    summary = {}
    for arm, rows in arms.items():
        times = sorted(row["ms"] for row in rows)
        summary[arm] = {
            "hit_at_1": round(sum(row["rank"] == 1 for row in rows) / len(rows), 3),
            "hit_at_5": round(sum(row["rank"] is not None for row in rows) / len(rows), 3),
            "mrr_at_5": round(sum(1 / row["rank"] for row in rows if row["rank"]) / len(rows), 3),
            "mean_ms": round(statistics.mean(times), 1),
            "p95_ms": times[min(len(times) - 1, math.ceil(.95 * len(times)) - 1)],
            "misses": [row["fact_id"] for row in rows if row["rank"] is None],
        }
    return {"scope": "public AWS Glue facts and captured official body only",
            "corpus_chunks": len(documents), "queries": len(questions),
            "embedding_dimensions": dimensions, "corpus_embedding_ms": corpus_embedding_ms,
            "arms": summary, "rows": arms}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
