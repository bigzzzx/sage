"""Retrieval behavior without a model, network, or persisted Chroma state."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.rag import (KnowledgeDocument, KnowledgeRetriever,
                              _expanded_query, _focused_excerpt)


class RagRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = KnowledgeRetriever.__new__(KnowledgeRetriever)
        self.retriever._settings = SimpleNamespace(rag_retrieve_k=12, rag_rerank_k=5)
        self.retriever._semantic_embeddings = False
        self.retriever._collection = None
        self.retriever._reranker = None

    def test_full_corpus_bm25_recalls_exact_term_and_respects_scope(self) -> None:
        noise = tuple(KnowledgeDocument(f"noise:{i}", "unrelated", "case", "other data",
                                        "glue") for i in range(100))
        target = KnowledgeDocument("case:target", "AccessDenied", "case",
                                   "S3 ListBucket permission denied", "glue")
        wrong_service = KnowledgeDocument("case:wrong", "AccessDenied", "case",
                                          "S3 ListBucket permission denied", "athena")
        with patch("app.services.rag.load_knowledge_documents",
                   return_value=noise + (target, wrong_service)):
            results = self.retriever.search(query="S3 ListBucket AccessDenied",
                                            service_id="glue", limit=3)
        self.assertEqual(results[0].document.document_id, "case:target")
        self.assertTrue(all(item.document.service_id == "glue" for item in results))

    def test_final_context_deduplicates_chunks_and_filters_source_type(self) -> None:
        docs = (
            KnowledgeDocument("doc:x:chunk:001", "NAT", "official_doc", "网络出口 NAT", "glue"),
            KnowledgeDocument("doc:x:chunk:002", "NAT", "official_doc", "网络出口 NAT", "glue"),
            KnowledgeDocument("doc:y", "NAT", "official_doc", "网络出口 NAT 网关", "glue"),
            KnowledgeDocument("case:z", "NAT", "case", "网络出口 NAT 网关", "glue"),
        )
        with patch("app.services.rag.load_knowledge_documents", return_value=docs):
            results = self.retriever.search(query="NAT 网络出口", service_id="glue", limit=3,
                                            source_types=["official_doc"])
        self.assertEqual(len(results), 2)
        self.assertEqual(len({item.document.document_id.split(":chunk:")[0] for item in results}), 2)
        self.assertTrue(all(item.document.source_type == "official_doc" for item in results))

    def test_expansion_is_bounded_and_excerpt_finds_late_answer(self) -> None:
        self.assertIn("startup script", _expanded_query("启动脚本无法清除"))
        excerpt = _focused_excerpt("背景" * 300 + "关键结论 NAT 网关" + "附录" * 300,
                                   "NAT 网关")
        self.assertIn("关键结论 NAT 网关", excerpt)
        self.assertLessEqual(len(excerpt), 502)

    def test_real_semantic_path_fuses_with_bm25_when_configured(self) -> None:
        lexical = KnowledgeDocument("lexical", "AccessDenied", "official_doc",
                                    "S3 ListBucket denied", "glue")
        semantic = KnowledgeDocument("semantic", "Permissions", "official_doc",
                                     "Check the bucket policy for missing permissions", "glue")
        collection = MagicMock()
        collection.count.return_value = 2
        collection.query.return_value = {
            "ids": [["semantic"]], "documents": [[semantic.content]],
            "metadatas": [[{"title": semantic.title, "source_type": "official_doc",
                            "service_id": "glue", "capability_id": "", "url": ""}]],
        }
        self.retriever._collection = collection
        self.retriever._semantic_embeddings = True
        with patch("app.services.rag.load_knowledge_documents",
                   return_value=(lexical, semantic)), \
             patch.object(self.retriever, "_embed", return_value=[[0.1, 0.2]]):
            results = self.retriever.search(query="AccessDenied", service_id="glue",
                                            limit=2, source_types=["official_doc"])
        self.assertEqual({item.document.document_id for item in results},
                         {"lexical", "semantic"})
        self.assertTrue(all(item.retrieval_method == "hybrid_rrf" for item in results))
        self.assertIn("source_type", str(collection.query.call_args.kwargs["where"]))

    def test_semantic_failure_retains_keyword_results(self) -> None:
        target = KnowledgeDocument("target", "AccessDenied", "official_doc",
                                   "S3 ListBucket denied", "glue")
        self.retriever._semantic_embeddings = True
        with patch("app.services.rag.load_knowledge_documents", return_value=(target,)), \
             patch.object(self.retriever, "_semantic_search", side_effect=RuntimeError("offline")), \
             patch("app.services.rag.logger"):
            results = self.retriever.search(query="AccessDenied", service_id="glue")
        self.assertEqual(results[0].document.document_id, "target")
        self.assertEqual(results[0].retrieval_method, "bm25_rrf")

    def test_archived_document_is_not_resurrected_by_stale_vector_index(self) -> None:
        active = KnowledgeDocument("active", "NAT", "official_doc", "NAT gateway", "glue")
        collection = MagicMock()
        collection.count.return_value = 2
        collection.query.return_value = {
            "ids": [["managed:archived"]],
            "documents": [["NAT gateway old content"]],
            "metadatas": [[{"service_id": "glue", "source_type": "case"}]],
        }
        self.retriever._collection = collection
        self.retriever._semantic_embeddings = True
        with patch("app.services.rag.load_knowledge_documents", return_value=(active,)), \
             patch.object(self.retriever, "_embed", return_value=[[0.1, 0.2]]):
            results = self.retriever.search(query="NAT gateway", service_id="glue")
        self.assertEqual([item.document.document_id for item in results], ["active"])


if __name__ == "__main__":
    unittest.main()
