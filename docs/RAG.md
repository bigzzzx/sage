# SAGE RAG Design

SAGE grounds question generation and personalized learning plans in case records,
learning paths, and official documentation references. Case records are training
material, not an authoritative substitute for AWS documentation.

## Runtime flow

1. The backend builds a corpus from `data/cases`, `data/taxonomy/learning_path`,
   `data/evals/glue_public_facts.json`, and the `doc_refs` attached to each service
   capability. Case indexing includes symptoms,
   root causes, troubleshooting clues, resolution steps, and other available fields.
   An official reference has source type `official_doc` only when its exact URL has
   a valid local body snapshot; otherwise it is an `official_ref` (metadata/link only).
   Glue public facts are `curated_fact` sources.
2. Long records are split into overlapping chunks before indexing.
3. ChromaDB persists those chunks under `data/chroma`.
4. Retrieval is constrained by `service_id` and, when available, capability IDs from diagnosis.
5. The full service/capability-filtered corpus is ranked with BM25, both for the
   original query and a bounded bilingual alias expansion. When real semantic
   embeddings are configured, Chroma vector neighbors form a third candidate path.
   Reciprocal rank fusion (RRF) merges the ranked lists; an optional locally
   available or remote HTTP reranker reranks that merged pool. The final context takes at
   most one chunk per source document and extracts a query-focused excerpt.
6. Without an embedding endpoint or installed local embedding model, retrieval
   uses full-corpus BM25 only. The hash vectors in the persisted Chroma collection
   are never treated as semantic candidates; this is not semantic search.
7. The question and planning Agents receive only the top retrieved sources. Source IDs, excerpts,
   scores, and URLs are persisted with the assessment and displayed on the result page.
8. Assessment generation, ticket creation, and post-assessment learning-plan generation
   all use the same service-scoped retrieval entry point. The Glue question validator
   still requires its curated fact IDs; its facts are loaded into the shared corpus.
   Ticket generation uses cases and learning paths for scenario design only, and allows
   only curated facts and captured official excerpts to support technical claims.
   Learning-plan concept URLs are similarly limited to curated facts and captured
   official excerpts; a metadata-only `official_ref` is not citation evidence.
   The report/diagnosis and live customer-dialogue paths are separate from this scope.

## Embedding configuration

DeepSeek chat models do not provide embeddings. SAGE accepts a separate OpenAI-compatible
embedding service, an installed local SentenceTransformer, or the existing HTTP `/embed`
service. For the latter, open the SSH tunnel in its own terminal from the repository root:

```powershell
.\scripts\start_rag_tunnel.ps1 -HostAlias remote-rag-host
```

Then configure `backend/.env` and restart the backend:

```env
EMBEDDING_PROVIDER=remote_http
EMBEDDING_BASE_URL=http://127.0.0.1:18081
RAG_COLLECTION=sage_knowledge_remote
RAG_EMBED_BATCH_SIZE=16
RAG_RERANKER_ENABLED=false
RAG_RERANKER_PROVIDER=remote_http
RAG_RERANKER_BASE_URL=http://127.0.0.1:18082
RAG_RERANKER_BATCH_SIZE=2
```

Use a **new collection name** when changing embedding model or dimensions; the old
collection is preserved. Plain HTTP model endpoints are allowed only on localhost;
use the SSH tunnel, not a public unencrypted URL. The two remote services do not
require an API key through this adapter. The case corpus and queries are sent to
the server during indexing/search, so enable it only on an authorized host.
Reranking is opt-in because the 2026-09-30 comparison did not show an overall gain
and substantially increased latency. Set `RAG_RERANKER_ENABLED=true` only for a
controlled trial. If the tunnel is unavailable during backend startup, lexical
retrieval remains usable; restart the backend after restoring the tunnel to activate
the semantic collection.

For an OpenAI-compatible embedding service instead, use:

```env
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_API_KEY=replace-me
EMBEDDING_BASE_URL=https://your-embedding-endpoint/v1
EMBEDDING_MODEL=your-embedding-model
```

The RAG storage settings are:

```env
RAG_BACKEND=chroma
RAG_CHROMA_PATH=data/chroma
RAG_COLLECTION=sage_knowledge
```

## Capture official excerpts and refresh the index

Run from the `backend` directory (use its virtual environment):

```bash
python -m app.scripts.refresh_official_docs --service glue
python -m app.scripts.reindex_rag
python -m app.scripts.rag_coverage
```

Omit `--service glue` to attempt every official URL already listed in the taxonomy;
`--refresh` replaces existing snapshots. The capture script checks the AWS documentation
host, prefers a reachable Chinese page, and reports unavailable URLs rather than
inventing body text. It stores excerpts, not complete pages. Review AWS terms and
refresh stale excerpts before using them in a deployment.

Both `data/chroma` and `data/knowledge/official_docs` are ignored by Git. A fresh
checkout therefore starts with metadata-only documentation references until the
capture and reindex commands have been run. A running backend may need a restart to
clear its in-process corpus cache after refreshing snapshots.

## Reviewed knowledge contributions

The manager navigation has a Knowledge Base page (`/dashboard/knowledge`).
Managers can create a case draft with symptom, investigation, root cause, solution,
and verification, or save an AWS documentation URL. A documentation draft cannot
be published until the server captures and previews the official body from an
allowlisted HTTPS AWS documentation host. Manually pasted content is never
accepted as an `official_doc` source. Both types require explicit manager review
and publication before they enter RAG. Published rows are stored in the
`knowledge_entries` table; archived rows are omitted from future lexical search,
and stale vector hits are filtered against the active corpus.

Members may propose a teaching case from one of their own closed, profile-matched
simulated tickets. The report is prefilled only as an editable draft; simulated
cases are not real customer evidence. Their submission is `submitted` and cannot
be published by a member. Basic account-ID, access-key, and email checks run on
case text, but managers must still review privacy, accuracy, and source support.

Publishing or archiving rebuilds the Chroma index. If the embedding provider is
unavailable, the entry is marked `pending` for vector indexing, but the new
published corpus is immediately usable through BM25. The manager can retry from
the page. File/PDF uploads, batch ingestion, and automated PII review are not in
this first version; only structured case text and official documentation URLs are
supported.

`rag_coverage` is read-only. It reports configured services, services with chunks,
chunk counts by source type, and official references with captured excerpts. A
reference count is not the same as a count of distinct reachable pages.
Services without indexed material return no retrieved context; this does not imply
that a model-generated answer for such a service is grounded. A missing excerpt
cannot be promoted to evidence simply because its URL is in the taxonomy.

## Evaluation

Run `python -m app.scripts.benchmark_rag` for the small checked-in retrieval fixture.
Use `--queries ../data/evals/rag_queries_diagnostic.json` for a second set of
paraphrased cases, and `--top-k 1` to inspect first-result quality. The output
includes Hit@1, Hit@K, MRR@K, authoritative-source coverage, retriever initialization
time, and per-query latency. Lexical term preparation happens once during initialization.
These
small fixtures are smoke signals, not broad quality measurements. Future evaluation
should use independently labelled `blind spot -> expected source` pairs and report
Recall@5, source coverage, citation support, and the percentage of plans whose
critical or major gaps have at least one relevant source. Coverage should be
expanded beyond the currently documented services before claiming broad AWS support.
