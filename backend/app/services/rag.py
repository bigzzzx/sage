"""Persistent knowledge retrieval for SAGE.

The corpus is built from project materials of distinct trust levels. An
OpenAI-compatible embedding endpoint enables semantic retrieval; without one,
the same persistent index remains usable with deterministic lexical ranking.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from app.config import get_settings
from app.services.remote_rag_models import RemoteRagModels
from app.services.taxonomy import get_full_taxonomy

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OFFICIAL_DOC_CACHE_DIR = DATA_DIR / "knowledge" / "official_docs"
OFFICIAL_HOSTS = {"docs.amazonaws.cn", "docs.aws.amazon.com"}
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
HASH_VECTOR_SIZE = 256
logger = logging.getLogger(__name__)


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


def _official_snapshot(url: str) -> dict | None:
    """Use only a locally captured excerpt for the exact allowlisted source URL."""
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS
            or parsed.port not in {None, 443} or parsed.username or parsed.password):
        return None
    path = OFFICIAL_DOC_CACHE_DIR / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")
    try:
        snapshot = _read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(snapshot, dict):
        return None
    resolved = urlparse(snapshot.get("resolved_url", ""))
    if (snapshot.get("source_url") != url or resolved.scheme != "https"
            or resolved.hostname not in OFFICIAL_HOSTS or resolved.port not in {None, 443}
            or resolved.username or resolved.password
            or not isinstance(snapshot.get("text"), str)
            or not snapshot["text"].strip()
            or snapshot.get("sha256") != hashlib.sha256(snapshot["text"].encode("utf-8")).hexdigest()):
        return None
    return snapshot


def _case_content(case: dict) -> str:
    """Index both generations of the case schema, keeping evidence-bearing fields."""
    sections = [
        ("案例摘要", case.get("summary")),
        ("客户现象", case.get("customer_symptom") or case.get("customer_problem")),
        ("问题根因", case.get("root_cause")),
        ("解决方案", case.get("resolution")),
        ("排查与解决步骤", case.get("resolution_steps")),
        ("排查线索", case.get("troubleshooting_clues")),
        ("关键知识点", case.get("key_knowledge_points") or case.get("key_skills")),
        ("预防建议", case.get("prevention_advice")),
    ]
    parts = []
    for label, value in sections:
        if isinstance(value, str) and value.strip():
            parts.append(f"{label}：{value.strip()}")
        elif isinstance(value, list):
            parts.extend(f"{label}：{item.strip()}" for item in value
                         if isinstance(item, str) and item.strip())
    for message in case.get("conversation") or []:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            parts.append(f"对话 {message.get('role', '')}：{message['content']}")
    return "\n".join(parts)


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
                    snapshot = _official_snapshot(ref.get("url", ""))
                    documents.append(KnowledgeDocument(
                        document_id=f"doc:{service_id}:{capability_id}:{index}",
                        title=title,
                        source_type="official_doc" if snapshot else "official_ref",
                        content=" ".join(filter(None, [
                            title, ref.get("summary", ""), capability.get("name", ""),
                            capability.get("description", ""),
                            f"官方正文节选：{snapshot['text']}" if snapshot else "",
                        ])),
                        service_id=service_id,
                        capability_id=capability_id,
                        url=snapshot["resolved_url"] if snapshot else ref.get("url", ""),
                    ))

    # Curated public facts share the same corpus and retrieval boundary as all
    # other sources, but retain a distinct trust tier for generation.
    from app.services.glue_sources import load_glue_facts
    for fact in load_glue_facts():
        snapshot = _official_snapshot(fact["source"])
        documents.append(KnowledgeDocument(
            document_id=f"fact:glue:{fact['id']}",
            title=fact["id"],
            source_type="curated_fact",
            content=fact["fact"],
            service_id="glue",
            url=snapshot["resolved_url"] if snapshot else fact["source"],
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
        documents.append(KnowledgeDocument(
            document_id=f"case:{path.stem}",
            title=case.get("title", path.stem),
            source_type="case",
            content=_case_content(case),
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

    # Database contributions are never trusted until a manager publishes them.
    from sqlalchemy import inspect
    from app.db import SessionLocal, engine
    from app.models import KnowledgeEntry
    if inspect(engine).has_table(KnowledgeEntry.__tablename__):
        with SessionLocal() as db:
            entries = db.query(KnowledgeEntry).filter_by(status="published").all()
            for entry in entries:
                if entry.content.strip():
                    documents.append(KnowledgeDocument(
                        document_id=f"managed:{entry.id}", title=entry.title,
                        source_type=entry.source_type, content=entry.content,
                        service_id=entry.service_id, capability_id=entry.capability_id,
                        url=entry.url,
                    ))

    chunked = [chunk for document in documents for chunk in _chunk_document(document)]
    return tuple(chunked)


def curated_fact_documents(service_id: str) -> list[KnowledgeDocument]:
    return [doc for doc in load_knowledge_documents()
            if doc.service_id == service_id and doc.source_type == "curated_fact"]


def format_curated_fact_context(service_id: str) -> str:
    facts = curated_fact_documents(service_id)
    return "\n".join(f"- [{doc.document_id.rsplit(':', 1)[-1]}] {doc.content} 官方依据：{doc.url}"
                     for doc in facts) or "（暂无已核验事实）"


def knowledge_coverage() -> dict:
    """Report what the corpus can actually retrieve, including empty services."""
    documents = load_knowledge_documents()
    indexed = Counter(doc.service_id for doc in documents)
    types = Counter(doc.source_type for doc in documents)
    services = []
    for track in get_full_taxonomy().get("tracks", []):
        for service in track.get("services", []):
            refs = [ref for cap in service.get("capabilities", [])
                    for ref in cap.get("doc_refs") or []]
            services.append({
                "profile_id": track["id"], "service_id": service["id"],
                "chunks": indexed[service["id"]],
                "official_refs": len(refs),
                "official_excerpts": sum(_official_snapshot(ref.get("url", "")) is not None
                                         for ref in refs),
            })
    return {"service_count": len(services),
            "services_with_chunks": sum(item["chunks"] > 0 for item in services),
            "chunk_count": len(documents), "chunks_by_type": dict(types),
            "services": services}


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


# Small, deterministic bilingual expansions. No generation-model call is made
# at retrieval time, and the original query remains a separate recall path.
QUERY_ALIASES = (
    ("爬虫", "crawler"), ("数据目录", "data catalog"),
    ("安全组", "security group"), ("网络出口", "NAT"),
    ("私网终端节点", "VPC endpoint"), ("启动脚本", "startup script"),
    ("主节点", "master node"), ("书签", "bookmark"),
    ("访问被拒", "AccessDenied"), ("列不存在", "COLUMN_NOT_FOUND"),
)


def _expanded_query(query: str) -> str:
    lower = query.casefold()
    additions = []
    for left, right in QUERY_ALIASES:
        if left.casefold() in lower and right.casefold() not in lower:
            additions.append(right)
        elif right.casefold() in lower and left.casefold() not in lower:
            additions.append(left)
    return query + (" " + " ".join(additions) if additions else "")


@lru_cache(maxsize=4096)
def _document_terms(title: str, content: str) -> tuple[str, ...]:
    return tuple(_terms(f"{title} {title} {content}"))


@lru_cache(maxsize=4096)
def _document_term_counts(title: str, content: str) -> Counter[str]:
    return Counter(_document_terms(title, content))


def _bm25_rank(query: str, documents: list[KnowledgeDocument]) -> list[tuple[KnowledgeDocument, float]]:
    """Full filtered-corpus lexical recall; never prefilter by hash vectors."""
    query_terms = set(_terms(query))
    if not query_terms or not documents:
        return []
    frequencies = [_document_term_counts(doc.title, doc.content) for doc in documents]
    lengths = [sum(freq.values()) for freq in frequencies]
    average_length = max(sum(lengths) / len(lengths), 1)
    dfs = Counter(term for freq in frequencies for term in query_terms if term in freq)
    ranked = []
    for doc, freq, length in zip(documents, frequencies, lengths):
        score = 0.0
        for term in query_terms:
            count = freq.get(term, 0)
            if not count:
                continue
            idf = math.log1p((len(documents) - dfs[term] + 0.5) / (dfs[term] + 0.5))
            score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average_length))
        if score > 0:
            ranked.append((doc, score))
    return sorted(ranked, key=lambda item: (-item[1], item[0].document_id))


def _root_document_id(document_id: str) -> str:
    return re.sub(r":chunk:\d+$", "", document_id)


def _fuse_rankings(
    rankings: list[list[KnowledgeDocument]], limit: int, method: str,
) -> list[RetrievedDocument]:
    """RRF merges independent paths without comparing incomparable raw scores."""
    fused: dict[str, float] = {}
    documents: dict[str, KnowledgeDocument] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            documents[doc.document_id] = doc
            fused[doc.document_id] = fused.get(doc.document_id, 0.0) + 1 / (60 + rank)
    ordered = sorted(fused, key=lambda doc_id: (-fused[doc_id], doc_id))
    if not ordered:
        return []
    highest = fused[ordered[0]]
    return [RetrievedDocument(documents[doc_id], round(fused[doc_id] / highest, 3), method)
            for doc_id in ordered[:limit]]


def _diversify(results: list[RetrievedDocument], limit: int) -> list[RetrievedDocument]:
    """Prevent adjacent chunks of one document from consuming the final budget."""
    selected, seen = [], set()
    for item in results:
        root = _root_document_id(item.document.document_id)
        if root in seen:
            continue
        seen.add(root)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


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
        self._remote_models: RemoteRagModels | None = None
        self._semantic_embeddings = False
        if settings.embedding_provider.lower() == "remote_http":
            if not settings.embedding_base_url:
                raise ValueError("EMBEDDING_BASE_URL is required for remote_http")
            self._remote_models = RemoteRagModels(
                embedding_url=settings.embedding_base_url,
                reranker_url=(settings.rag_reranker_base_url
                              if settings.rag_reranker_enabled
                              and settings.rag_reranker_provider.lower() == "remote_http" else ""),
            )
            self._semantic_embeddings = True
        elif settings.embedding_api_key and settings.embedding_base_url and self._embedding_model:
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

        if (settings.rag_reranker_enabled and self._semantic_embeddings
                and settings.rag_reranker_provider.lower() == "local"):
            try:
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder(
                    settings.rag_reranker_model,
                    device=settings.rag_model_device,
                    local_files_only=True,
                )
            except Exception:
                self._reranker = None
        elif (settings.rag_reranker_enabled and self._semantic_embeddings
              and settings.rag_reranker_provider.lower() == "remote_http"):
            if not settings.rag_reranker_base_url:
                raise ValueError("RAG_RERANKER_BASE_URL is required for remote_http")
            if self._remote_models is None:
                self._remote_models = RemoteRagModels(
                    reranker_url=settings.rag_reranker_base_url)

        self._chroma: Any | None = None
        self._collection: Any | None = None
        self._index_path: Path | None = None
        if settings.rag_backend.lower() == "chroma":
            self._init_chroma()
        # One-time lexical preparation belongs to retriever initialization,
        # not the first interactive query.
        for document in load_knowledge_documents():
            _document_term_counts(document.title, document.content)

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
            # The API remains usable when Chroma or the remote model is unavailable.
            logger.exception("RAG vector index unavailable; retaining BM25 retrieval")
            self._chroma = None
            self._collection = None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._remote_models and self._remote_models.embedding_endpoint:
            return self._remote_models.embed(texts)
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
        if not candidates:
            return candidates
        if self._remote_models and self._remote_models.reranker_endpoint:
            scores = self._remote_models.rerank(
                query, [item.document.content for item in candidates],
                batch_size=self._settings.rag_reranker_batch_size,
            )
        elif self._reranker:
            pairs = [(query, item.document.content) for item in candidates]
            scores = self._reranker.predict(pairs, show_progress_bar=False)
        else:
            return candidates
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
        digest.update((self._settings.embedding_base_url or "").encode())
        digest.update(("semantic" if self._semantic_embeddings else "hash").encode())
        for document in load_knowledge_documents():
            for value in (document.document_id, document.title, document.source_type,
                          document.service_id, document.capability_id, document.url,
                          document.content):
                digest.update(value.encode("utf-8"))
                digest.update(b"\0")
        return digest.hexdigest()

    def rebuild_index(self, force: bool = False) -> dict[str, Any]:
        if self._collection is None:
            return {"backend": "keyword", "indexed": 0, "skipped": True}

        if force:
            load_knowledge_documents.cache_clear()

        documents = list(load_knowledge_documents())
        signature = self._corpus_signature()
        if not force and self._index_path and self._index_path.exists():
            try:
                state = json.loads(self._index_path.read_text(encoding="utf-8"))
                if state.get("signature") == signature and self._collection.count() == len(documents):
                    return {"backend": "chroma", "indexed": len(documents), "skipped": True}
            except (OSError, json.JSONDecodeError):
                pass

        # Persist per-document fingerprints so a single reviewed contribution
        # does not re-embed the entire corpus. Changing the embedding model
        # invalidates every fingerprint even when text itself is unchanged.
        model_identity = "|".join((self._settings.embedding_provider or "hash",
                                   self._embedding_model or "",
                                   self._settings.embedding_base_url or "",
                                   "semantic" if self._semantic_embeddings else "hash"))
        hashes = {doc.document_id: hashlib.sha256(
            (model_identity + "\0" + doc.title + "\0" + doc.source_type + "\0"
             + doc.service_id + "\0" + doc.capability_id + "\0" + doc.url + "\0"
             + doc.content).encode("utf-8")).hexdigest() for doc in documents}
        old_hashes: dict[str, str] = {}
        if not force and self._index_path and self._index_path.exists():
            try:
                old_hashes = json.loads(self._index_path.read_text(encoding="utf-8")).get("hashes", {})
            except (OSError, json.JSONDecodeError):
                pass
        existing_ids = set(self._collection.get(include=[])["ids"])
        changed = [doc for doc in documents if force or doc.document_id not in existing_ids
                   or old_hashes.get(doc.document_id) != hashes[doc.document_id]]
        # Finish embedding before touching the existing collection. A failed
        # provider call must not erase a usable index.
        batch_size = self._settings.rag_embed_batch_size
        if batch_size < 1:
            raise ValueError("RAG_EMBED_BATCH_SIZE must be positive")
        batches = [changed[start:start + batch_size]
                   for start in range(0, len(changed), batch_size)]
        vectors = [self._embed([doc.content for doc in batch]) for batch in batches]
        if existing_ids and vectors:
            sample = self._collection.get(limit=1, include=["embeddings"])["embeddings"]
            if sample is not None and len(sample) and len(sample[0]) != len(vectors[0][0]):
                raise ValueError("Embedding dimension changed; configure a new RAG_COLLECTION"
                                 " instead of replacing the existing index")

        for batch, embeddings in zip(batches, vectors):
            self._collection.upsert(
                ids=[doc.document_id for doc in batch],
                documents=[doc.content for doc in batch],
                embeddings=embeddings,
                metadatas=[{
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "service_id": doc.service_id,
                    "capability_id": doc.capability_id,
                    "url": doc.url,
                } for doc in batch],
            )
        stale_ids = existing_ids - {doc.document_id for doc in documents}
        if stale_ids:
            self._collection.delete(ids=sorted(stale_ids))
        if self._index_path:
            self._index_path.write_text(
                json.dumps({"signature": signature, "count": len(documents), "hashes": hashes}, indent=2),
                encoding="utf-8",
            )
        return {"backend": "chroma", "indexed": len(documents), "updated": len(changed), "skipped": False}

    def _keyword_search(
        self, query: str, service_id: str, capability_ids: list[str], limit: int,
        source_types: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        documents = [
            doc for doc in load_knowledge_documents()
            if doc.service_id == service_id
            and (not source_types or doc.source_type in source_types)
            and (not capability_ids or not doc.capability_id or doc.capability_id in capability_ids)
        ]
        pool_size = max(limit * 4, self._settings.rag_retrieve_k)
        rankings = [[doc for doc, _ in _bm25_rank(query, documents)[:pool_size]]]
        expanded = _expanded_query(query)
        if expanded != query:
            rankings.append([doc for doc, _ in _bm25_rank(expanded, documents)[:pool_size]])
        fused = _fuse_rankings(rankings, pool_size * 2, "bm25_rrf")
        return _diversify(fused, limit)

    def _semantic_search(
        self, query: str, service_id: str, capability_filter: set[str],
        source_types: list[str] | None, limit: int,
    ) -> list[KnowledgeDocument]:
        if not self._semantic_embeddings or self._collection is None:
            return []
        count = self._collection.count()
        if not count:
            return []
        clauses: list[dict] = [{"service_id": service_id}]
        if capability_filter:
            clauses.append({"$or": [
                {"capability_id": {"$in": sorted(capability_filter)}},
                {"capability_id": ""},
            ]})
        if source_types:
            clauses.append({"source_type": {"$in": sorted(set(source_types))}})
        where: dict = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        result = self._collection.query(
            query_embeddings=[self._embed([query])[0]],
            n_results=min(count, limit), where=where,
            include=["documents", "metadatas"],
        )
        by_id = {doc.document_id: doc for doc in load_knowledge_documents()}
        hits = []
        for doc_id in result.get("ids", [[]])[0]:
            # An out-of-date vector index must never resurrect an archived item.
            if doc_id in by_id:
                hits.append(by_id[doc_id])
        return hits

    def search(
        self,
        *,
        query: str,
        service_id: str,
        capability_ids: list[str] | None = None,
        limit: int = 5,
        source_types: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        capability_filter = set(capability_ids or [])
        if limit < 1:
            return []
        documents = [doc for doc in load_knowledge_documents()
                     if doc.service_id == service_id
                     and (not source_types or doc.source_type in source_types)
                     and (not capability_filter or not doc.capability_id
                          or doc.capability_id in capability_filter)]
        if not documents:
            return []
        pool_size = max(limit * 4, self._settings.rag_retrieve_k,
                        self._settings.rag_rerank_k)
        rankings = [[doc for doc, _ in _bm25_rank(query, documents)[:pool_size]]]
        expanded = _expanded_query(query)
        if expanded != query:
            rankings.append([doc for doc, _ in _bm25_rank(expanded, documents)[:pool_size]])
        try:
            semantic = self._semantic_search(query, service_id, capability_filter,
                                             source_types, pool_size)
        except Exception:
            logger.exception("Semantic RAG recall failed; retaining BM25 results")
            semantic = []
        if semantic:
            rankings.append(semantic)
        candidates = _fuse_rankings(rankings, pool_size * len(rankings),
                                   "hybrid_rrf" if semantic else "bm25_rrf")
        remote_models = getattr(self, "_remote_models", None)
        if self._reranker or (remote_models and remote_models.reranker_endpoint):
            try:
                candidates = self._rerank(query, candidates)
            except Exception:
                logger.exception("RAG reranker failed; retaining fused results")
        return _diversify(candidates, limit)


@lru_cache(maxsize=1)
def get_retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever()


def retrieve_resources(
    *, query: str, service_id: str, capability_ids: list[str] | None = None,
    limit: int = 5, source_types: list[str] | None = None,
) -> list[RetrievedDocument]:
    return get_retriever().search(
        query=query, service_id=service_id, capability_ids=capability_ids,
        limit=limit, source_types=source_types,
    )


def _focused_excerpt(content: str, query: str, max_chars: int = 500) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    if len(text) <= max_chars or not query.strip():
        return text[:max_chars]
    terms = {term for term in _terms(query) if len(term) >= 2}
    lower = text.casefold()
    positions = [match.start() for term in terms
                 for match in list(re.finditer(re.escape(term.casefold()), lower))[:12]]
    if not positions:
        return text[:max_chars]
    starts = {0, max(0, len(text) - max_chars)}
    starts.update(max(0, min(pos - 80, len(text) - max_chars)) for pos in positions)
    best = max(starts, key=lambda start: (
        sum(start <= pos < start + max_chars for pos in positions), -start))
    prefix = "…" if best else ""
    suffix = "…" if best + max_chars < len(text) else ""
    return prefix + text[best:best + max_chars] + suffix


def format_retrieval_context(results: list[RetrievedDocument], query: str = "") -> str:
    if not results:
        return "(no knowledge sources matched)"
    lines = []
    for item in results:
        doc = item.document
        excerpt = _focused_excerpt(doc.content, query)
        lines.append(
            f"- [{doc.source_type}] {doc.title} (id={doc.document_id}, score={item.score})\n"
            f"  {excerpt}\n  URL: {doc.url or 'N/A'}"
        )
    return "\n".join(lines)
