"""Adapters for the existing /embed and /rerank HTTP inference services."""
from __future__ import annotations

import math
from urllib.parse import urlparse

import httpx


def _endpoint(base_url: str, route: str) -> str:
    parsed = urlparse(base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"})):
        raise ValueError("Remote RAG HTTP requires HTTPS or a localhost SSH tunnel")
    return base_url.rstrip("/") + route


class RemoteRagModels:
    def __init__(self, *, embedding_url: str = "", reranker_url: str = "") -> None:
        self.embedding_endpoint = _endpoint(embedding_url, "/embed") if embedding_url else ""
        self.reranker_endpoint = _endpoint(reranker_url, "/rerank") if reranker_url else ""
        self._client = httpx.Client(trust_env=False, timeout=httpx.Timeout(30, connect=3))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_endpoint:
            raise ValueError("Remote embedding endpoint is not configured")
        response = self._client.post(self.embedding_endpoint,
                                     json={"inputs": texts, "normalize": True})
        response.raise_for_status()
        vectors = response.json()
        if (not isinstance(vectors, list) or len(vectors) != len(texts)
                or not vectors or not all(isinstance(vector, list) and vector for vector in vectors)):
            raise ValueError("Invalid remote embedding response")
        dimensions = len(vectors[0])
        if any(len(vector) != dimensions or any(not isinstance(value, (float, int))
                  or not math.isfinite(value) for value in vector) for vector in vectors):
            raise ValueError("Invalid remote embedding dimensions or values")
        return vectors

    def rerank(self, query: str, texts: list[str], batch_size: int = 2) -> list[float]:
        if not self.reranker_endpoint:
            raise ValueError("Remote reranker endpoint is not configured")
        if batch_size < 1:
            raise ValueError("Rerank batch size must be positive")
        scores = [0.0] * len(texts)
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            response = self._client.post(self.reranker_endpoint,
                                         json={"query": query, "texts": batch})
            response.raise_for_status()
            ranked = response.json()
            if (not isinstance(ranked, list) or len(ranked) != len(batch)
                    or not all(isinstance(item, dict) for item in ranked)
                    or {item.get("index") for item in ranked} != set(range(len(batch)))):
                raise ValueError("Invalid remote reranker response")
            for item in ranked:
                score = item.get("score")
                if not isinstance(score, (int, float)) or not math.isfinite(score):
                    raise ValueError("Invalid remote reranker score")
                scores[start + item["index"]] = float(score)
        return scores

    def close(self) -> None:
        self._client.close()
