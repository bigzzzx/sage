"""HTTP protocol and safety checks for the opt-in remote RAG adapters."""
from __future__ import annotations

import json
import unittest

import httpx

from app.services.remote_rag_models import RemoteRagModels, _endpoint


class RemoteRagModelsTests(unittest.TestCase):
    def test_plain_http_requires_loopback(self) -> None:
        with self.assertRaises(ValueError):
            _endpoint("http://example.com:8081", "/embed")
        with self.assertRaises(ValueError):
            _endpoint("http://user:password@127.0.0.1:18081", "/embed")
        self.assertEqual(_endpoint("http://127.0.0.1:18081", "/embed"),
                         "http://127.0.0.1:18081/embed")

    def test_embed_and_small_batch_rerank_protocol(self) -> None:
        calls = []

        def reply(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            calls.append((request.url.path, payload))
            if request.url.path == "/embed":
                return httpx.Response(200, json=[[1.0, 0.0] for _ in payload["inputs"]])
            return httpx.Response(200, json=[
                {"index": index, "score": float(index + 1)}
                for index, _ in enumerate(payload["texts"])
            ])

        models = RemoteRagModels(embedding_url="http://127.0.0.1:18081",
                                 reranker_url="http://127.0.0.1:18082")
        models.close()
        models._client = httpx.Client(transport=httpx.MockTransport(reply), trust_env=False)
        try:
            self.assertEqual(models.embed(["one", "two"]), [[1.0, 0.0], [1.0, 0.0]])
            self.assertEqual(models.rerank("query", ["a", "b", "c", "d", "e"]),
                             [1.0, 2.0, 1.0, 2.0, 1.0])
        finally:
            models.close()
        self.assertEqual([len(payload["texts"]) for path, payload in calls if path == "/rerank"],
                         [2, 2, 1])

    def test_rejects_invalid_embedding_dimensions(self) -> None:
        models = RemoteRagModels(embedding_url="http://localhost:18081")
        models.close()
        models._client = httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[[1.0, 0.0], [1.0]])), trust_env=False)
        try:
            with self.assertRaises(ValueError):
                models.embed(["one", "two"])
        finally:
            models.close()


if __name__ == "__main__":
    unittest.main()
