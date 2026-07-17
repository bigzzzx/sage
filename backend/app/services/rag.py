"""Persistent knowledge retrieval for SAGE.

The corpus is built from reviewed project data and indexed in ChromaDB. An
OpenAI-compatible embedding endpoint enables semantic retrieval; without one,
the same persistent index remains usable with deterministic lexical ranking.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from app.config import get_settings
from app.services.taxonomy import get_full_taxonomy

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
HASH_VECTOR_SIZE = 256


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    title: str
    source_type: str
    content: str
    service_id: str
    capability_id: str = ""
    url: str = ""


@dataclass(frozen=True)
class RetrievedDocument:
    document: KnowledgeDocument
    score: float
    retrieval_method: str


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def _chunk_document(document: KnowledgeDocument) -> list[KnowledgeDocument]:
    text = re.sub(r"\s+", " ", document.content).strip()
    if len(text) <= CHUNK_SIZE:
        return [document]

    chunks: list[KnowledgeDocument] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for index, start in enumerate(range(0, len(text), step), start=1):
        chunk = text[start:start + CHUNK_SIZE].strip()
        if not chunk:
            continue
        chunks.append(KnowledgeDocument(
            document_id=f"{document.document_id}:chunk:{index:03d}",
            title=document.title,
            source_type=document.source_type,
            content=chunk,
            service_id=document.service_id,
            capability_id=document.capability_id,
            url=document.url,
        ))
        if start + CHUNK_SIZE >= len(text):
            break
    return chunks


@lru_cache(maxsize=1)
def load_knowledge_documents() -> tuple[KnowledgeDocument, ...]:
    """Build the reviewed corpus and split long records into retrieval chunks."""
    documents: list[KnowledgeDocument] = []
    taxonomy = get_full_taxonomy()
    service_ids = {
        service.get("id", "")
        for track in taxonomy.get("tracks", [])
        for service in track.get("services", [])
    }

    for track in taxonomy.get("tracks", []):
        for service in track.get("services", []):
            service_id = service.get("id", "")
            for capability in service.get("capabilities", []):
                capability_id = capability.get("id", "")
                for index, ref in enumerate(capability.get("doc_refs") or []):
                    title = ref.get("title", "Official documentation")
                    documents.append(KnowledgeDocument(
                        document_id=f"doc:{service_id}:{capability_id}:{index}",
                        title=title,
                        source_type="official_doc",
                        content=" ".join(filter(None, [
                            title, ref.get("summary", ""), capability.get("name", ""),
                            capability.get("description", ""),
                        ])),
                        service_id=service_id,
                        capability_id=capability_id,
                        url=ref.get("url", ""),
                    ))

    for path in sorted((DATA_DIR / "cases").glob("*.json")):
        if path.name.startswith("_"):
            continue
        case = _read_json(path)
        service_id = case.get("service_id", "") or next(
            (candidate for candidate in service_ids
             if path.stem.startswith(candidate.replace("_", "-"))),
            path.stem.split("-")[0],
        )
        messages = " ".join(
            message.get("content", "") for message in case.get("conversation", [])
            if isinstance(message, dict)
        )
        documents.append(KnowledgeDocument(
            document_id=f"case:{path.stem}",
            title=case.get("title", path.stem),
            source_type="case",
            content=" ".join(filter(None, [
                case.get("summary", ""), case.get("resolution", ""),
                " ".join(case.get("key_skills", [])), messages,
            ])),
            service_id=service_id,
            url=(case.get("references") or [""])[0],
        ))

    for path in sorted((DATA_DIR / "taxonomy" / "learning_path").glob("*.json")):
        data = _read_json(path)
        service_id = data.get("service_id") or path.stem
        for index, module in enumerate(data.get("modules", [])):
            content_parts = [module.get("name", "")]
            for level in ("basic", "intermediate", "advanced"):
                info = module.get(level) or {}
                content_parts.extend(info.get("topics", []))
                content_parts.extend(info.get("resources", []))
                content_parts.extend(info.get("labs", []))
            documents.append(KnowledgeDocument(
                document_id=f"path:{service_id}:{index}",
                title=f"{module.get('name', service_id)} learning path",
                source_type="learning_path",
                content=" ".join(content_parts),
                service_id=service_id,
            ))

    chunked = [chunk for document in documents for chunk in _chunk_document(document)]
    return tuple(chunked)


def _terms(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower())
    ascii_terms = re.findall(r"[a-z0-9_./-]{2,}", normalized)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    chinese_bigrams = [chinese[i:i + 2] for i in range(max(0, len(chinese) - 1))]
    return ascii_terms + chinese_bigrams


def _lexical_score(query: str, content: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    haystack = content.lower()
    return sum(1 for term in query_terms if term in haystack) / len(query_terms)


def _hash_embedding(text: str) -> list[float]:
    """Deterministic fallback so local development does not need a model."""
    vector = [0.0] * HASH_VECTOR_SIZE
    for term in _terms(text):
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % HASH_VECTOR_SIZE
        sign = 1.0 if digest[4] % 2 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class KnowledgeRetriever:
    """Chroma-backed retriever with an OpenAI-compatible embedding adapter."""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._embedding_model = settings.embedding_model
        self._client: OpenAI | None = None
        self._local_embedding: Any | None = None
        self._reranker: Any | None = None
        self._semantic_embeddings = False
        if settings.embedding_api_key and settings.embedding_base_url and self._embedding_model:
            self._client = OpenAI(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                http_client=httpx.Client(trust_env=False),
            )
            self._semantic_embeddings = True
        elif settings.embedding_provider.lower() in {"local", "sentence_transformers"}:
            try:
                from sentence_transformers import SentenceTransformer

                self._local_embedding = SentenceTransformer(
                    self._embedding_model,
                    device=settings.rag_model_device,
                    local_files_only=True,
                )
                self._semantic_embeddings = True
            except Exception:
                self._local_embedding = None

        if settings.rag_reranker_enabled and self._semantic_embeddings:
            try:
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder(
                    settings.rag_reranker_model,
                    device=settings.rag_model_device,
                    local_files_only=True,
                )
            except Exception:
                self._reranker = None

        self._chroma: Any | None = None
        self._collection: Any | None = None
        self._index_path: Path | None = None
        if settings.rag_backend.lower() == "chroma":
            self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb

            path = Path(self._settings.rag_chroma_path)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[3] / path
            path.mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(path=str(path))
            self._collection = self._chroma.get_or_create_collection(
                name=self._settings.rag_collection,
                metadata={"hnsw:space": "cosine"},
            )
            self._index_path = path / f"{self._settings.rag_collection}.index.json"
            self.rebuild_index()
        except Exception:
            # The API remains usable when Chroma is not installed yet.
            self._chroma = None
            self._collection = None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._client:
            response = self._client.embeddings.create(model=self._embedding_model, input=texts)
            return [item.embedding for item in response.data]
        if self._local_embedding:
            return self._local_embedding.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()
        return [_hash_embedding(text) for text in texts]

    def _rerank(self, query: str, candidates: list[RetrievedDocument]) -> list[RetrievedDocument]:
        if not self._reranker or not candidates:
            return candidates
        pairs = [(query, item.document.content) for item in candidates]
        scores = self._reranker.predict(pairs, show_progress_bar=False)
        reranked: list[RetrievedDocument] = []
        for item, raw_score in zip(candidates, scores):
            probability = 1.0 / (1.0 + math.exp(-float(raw_score)))
            score = round(0.85 * probability + 0.15 * item.score, 3)
            reranked.append(RetrievedDocument(
                document=item.document,
                score=score,
                retrieval_method="chroma_hybrid_rerank",
            ))
        return sorted(reranked, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_size = math.sqrt(sum(a * a for a in left))
        right_size = math.sqrt(sum(b * b for b in right))
        return numerator / (left_size * right_size) if left_size and right_size else 0.0

    def _corpus_signature(self) -> str:
        digest = hashlib.sha256()
        digest.update((self._settings.embedding_provider or "hash").encode())
        digest.update((self._embedding_model or "").encode())
        digest.update(("semantic" if self._semantic_embeddings else "hash").encode())
        for document in load_knowledge_documents():
            digest.update(document.document_id.encode())
            digest.update(document.content.encode("utf-8"))
        return digest.hexdigest()

    def rebuild_index(self, force: bool = False) -> dict[str, Any]:
        if self._collection is None:
            return {"backend": "keyword", "indexed": 0, "skipped": True}

        documents = list(load_knowledge_documents())
        signature = self._corpus_signature()
        if not force and self._index_path and self._index_path.exists():
            try:
                state = json.loads(self._index_path.read_text(encoding="utf-8"))
                if state.get("signature") == signature and self._collection.count() == len(documents):
                    return {"backend": "chroma", "indexed": len(documents), "skipped": True}
            except (OSError, json.JSONDecodeError):
                pass

        # Chroma collections have an immutable embedding dimension. Recreate
        # the collection when switching from fallback vectors to a real model.
        if self._collection.count() > 0:
            self._chroma.delete_collection(name=self._settings.rag_collection)
            self._collection = self._chroma.get_or_create_collection(
                name=self._settings.rag_collection,
                metadata={"hnsw:space": "cosine"},
            )

        for start in range(0, len(documents), 64):
            batch = documents[start:start + 64]
            self._collection.upsert(
                ids=[doc.document_id for doc in batch],
                documents=[doc.content for doc in batch],
                embeddings=self._embed([doc.content for doc in batch]),
                metadatas=[{
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "service_id": doc.service_id,
                    "capability_id": doc.capability_id,
                    "url": doc.url,
                } for doc in batch],
            )
        if self._index_path:
            self._index_path.write_text(
                json.dumps({"signature": signature, "count": len(documents)}, indent=2),
                encoding="utf-8",
            )
        return {"backend": "chroma", "indexed": len(documents), "skipped": False}

    def _keyword_search(
        self, query: str, service_id: str, capability_ids: list[str], limit: int
    ) -> list[RetrievedDocument]:
        candidates = [
            doc for doc in load_knowledge_documents()
            if doc.service_id == service_id
            and (not capability_ids or not doc.capability_id or doc.capability_id in capability_ids)
        ]
        ranked = sorted(
            candidates,
            key=lambda doc: _lexical_score(query, f"{doc.title} {doc.content}"),
            reverse=True,
        )
        return [RetrievedDocument(
            document=doc,
            score=round(_lexical_score(query, f"{doc.title} {doc.content}"), 3),
            retrieval_method="keyword_fallback",
        ) for doc in ranked[:limit]]

    def search(
        self,
        *,
        query: str,
        service_id: str,
        capability_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievedDocument]:
        capability_filter = set(capability_ids or [])
        if self._collection is None:
            return self._keyword_search(query, service_id, list(capability_filter), limit)

        count = self._collection.count()
        if not count:
            return []
        result = self._collection.query(
            query_embeddings=[self._embed([query])[0]],
            n_results=count,
            where={"service_id": service_id},
            include=["documents", "metadatas", "distances"],
        )
        documents_by_id = {doc.document_id: doc for doc in load_knowledge_documents()}
        candidates: list[RetrievedDocument] = []
        ids = result.get("ids", [[]])[0]
        texts = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        semantic = self._semantic_embeddings
        for document_id, text, metadata, distance in zip(ids, texts, metadatas, distances):
            document = documents_by_id.get(document_id)
            if not document:
                document = KnowledgeDocument(
                    document_id=document_id,
                    title=metadata.get("title", document_id),
                    source_type=metadata.get("source_type", "unknown"),
                    content=text or "",
                    service_id=metadata.get("service_id", service_id),
                    capability_id=metadata.get("capability_id", ""),
                    url=metadata.get("url", ""),
                )
            if capability_filter and document.capability_id and document.capability_id not in capability_filter:
                continue
            lexical = _lexical_score(query, f"{document.title} {document.content}")
            vector_score = max(0.0, min(1.0, 1.0 - float(distance)))
            score = 0.8 * vector_score + 0.2 * lexical if semantic else lexical
            candidates.append(RetrievedDocument(
                document=document,
                score=round(score, 3),
                retrieval_method="chroma_hybrid" if semantic else "chroma_keyword_fallback",
            ))
        candidates.sort(key=lambda item: item.score, reverse=True)
        candidates = candidates[:max(limit, self._settings.rag_retrieve_k)]
        if self._reranker:
            candidates = self._rerank(query, candidates)
            return candidates[:self._settings.rag_rerank_k]
        return candidates[:limit]


@lru_cache(maxsize=1)
def get_retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever()


def retrieve_resources(
    *, query: str, service_id: str, capability_ids: list[str] | None = None, limit: int = 5
) -> list[RetrievedDocument]:
    return get_retriever().search(
        query=query, service_id=service_id, capability_ids=capability_ids, limit=limit
    )


def format_retrieval_context(results: list[RetrievedDocument]) -> str:
    if not results:
        return "(no knowledge sources matched)"
    lines = []
    for item in results:
        doc = item.document
        excerpt = re.sub(r"\s+", " ", doc.content).strip()[:500]
        lines.append(
            f"- [{doc.source_type}] {doc.title} (id={doc.document_id}, score={item.score})\n"
            f"  {excerpt}\n  URL: {doc.url or 'N/A'}"
        )
    return "\n".join(lines)
