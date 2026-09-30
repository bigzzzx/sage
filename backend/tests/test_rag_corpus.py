"""Check that RAG indexes evidence from both case formats and vetted snapshots."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from app.services.rag import (KnowledgeDocument, KnowledgeRetriever, _case_content, _official_snapshot,
                              curated_fact_documents, knowledge_coverage,
                              load_knowledge_documents)


class RagCorpusTests(unittest.TestCase):
    def test_incremental_index_only_embeds_changed_document(self) -> None:
        class Collection:
            def __init__(self):
                self.rows = {}
            def get(self, include=None, limit=None):
                return {"ids": list(self.rows)[:limit] if limit else list(self.rows),
                        "embeddings": [self.rows[key] for key in list(self.rows)[:limit or None]]}
            def count(self):
                return len(self.rows)
            def upsert(self, ids, documents, embeddings, metadatas):
                self.rows.update(zip(ids, embeddings))
            def delete(self, ids):
                for key in ids:
                    self.rows.pop(key)
        with tempfile.TemporaryDirectory() as directory:
            retriever = KnowledgeRetriever.__new__(KnowledgeRetriever)
            retriever._collection = Collection()
            retriever._settings = SimpleNamespace(embedding_provider="hash", embedding_base_url="",
                                                  rag_embed_batch_size=10)
            retriever._embedding_model = "test"
            retriever._semantic_embeddings = False
            retriever._index_path = Path(directory) / "index.json"
            inputs = []
            retriever._embed = lambda texts: inputs.extend(texts) or [[0.1, 0.2] for _ in texts]
            docs = [KnowledgeDocument("a", "A", "case", "first", "glue"),
                    KnowledgeDocument("b", "B", "case", "second", "glue")]
            with patch("app.services.rag.load_knowledge_documents", return_value=docs):
                self.assertEqual(retriever.rebuild_index()["updated"], 2)
            inputs.clear()
            docs[1] = KnowledgeDocument("b", "B", "case", "second revised", "glue")
            with patch("app.services.rag.load_knowledge_documents", return_value=docs):
                self.assertEqual(retriever.rebuild_index()["updated"], 1)
            self.assertEqual(inputs, ["second revised"])

    def test_case_content_includes_new_schema_evidence(self) -> None:
        case = {
            "summary": "Athena 看不到表",
            "root_cause": "Lake Formation 没有给新角色授权",
            "resolution_steps": ["检查目录权限", "给新角色授予库表权限"],
            "troubleshooting_clues": ["IAM 已授权但目录不可见"],
            "key_knowledge_points": ["Lake Formation 与 IAM 权限不同"],
        }
        content = _case_content(case)
        for expected in ("Lake Formation 没有给新角色授权", "给新角色授予库表权限",
                         "IAM 已授权但目录不可见", "Lake Formation 与 IAM 权限不同"):
            self.assertIn(expected, content)

    def test_actual_case_is_retrievable_with_root_cause(self) -> None:
        chunks = [doc.content for doc in load_knowledge_documents()
                  if doc.document_id.startswith("case:athena-003-lake-formation-role-grant-missing")]
        self.assertTrue(chunks)
        self.assertIn("问题根因", " ".join(chunks))
        self.assertIn("排查线索", " ".join(chunks))

    def test_snapshot_must_match_original_and_official_host(self) -> None:
        url = "https://docs.amazonaws.cn/glue/latest/dg/example.html"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / (hashlib.sha256(url.encode()).hexdigest() + ".json")
            with patch("app.services.rag.OFFICIAL_DOC_CACHE_DIR", Path(directory)):
                text = "已核验的官方正文节选"
                target.write_text(json.dumps({"source_url": url, "resolved_url": url,
                                              "text": text,
                                              "sha256": hashlib.sha256(text.encode()).hexdigest()}),
                                  encoding="utf-8")
                self.assertEqual(_official_snapshot(url)["text"], "已核验的官方正文节选")
                target.write_text(json.dumps({"source_url": url,
                                              "resolved_url": "https://example.com/fake",
                                              "text": "伪造正文",
                                              "sha256": hashlib.sha256("伪造正文".encode()).hexdigest()}),
                                  encoding="utf-8")
                self.assertIsNone(_official_snapshot(url))

    def test_coverage_includes_empty_services(self) -> None:
        report = knowledge_coverage()
        self.assertGreater(report["service_count"], report["services_with_chunks"])
        self.assertEqual(report["chunk_count"], sum(report["chunks_by_type"].values()))

    def test_curated_glue_facts_share_corpus_and_references_are_not_excerpts(self) -> None:
        self.assertGreaterEqual(len(curated_fact_documents("glue")), 13)
        self.assertEqual(curated_fact_documents("athena"), [])
        docs = load_knowledge_documents()
        self.assertTrue(any(doc.source_type == "curated_fact" for doc in docs))
        self.assertTrue(any(doc.source_type == "official_ref" for doc in docs))


if __name__ == "__main__":
    unittest.main()
