# SAGE RAG Design

SAGE grounds question generation and personalized learning plans in reviewed internal cases,
learning paths, and official documentation references.

## Runtime flow

1. The backend builds a curated corpus from `data/cases`, `data/taxonomy/learning_path`, and the
   `doc_refs` attached to each service capability.
2. Long records are split into overlapping chunks before indexing.
3. ChromaDB persists those chunks under `data/chroma`.
4. Retrieval is constrained by `service_id` and, when available, capability IDs from diagnosis.
5. With an OpenAI-compatible embedding endpoint configured, SAGE uses hybrid ranking: 80% cosine
   similarity and 20% lexical score.
6. Without an embedding endpoint, the persistent Chroma index remains usable with deterministic
   keyword ranking. This is a development fallback, not semantic search.
7. The question and planning Agents receive only the top retrieved sources. Source IDs, excerpts,
   scores, and URLs are persisted with the assessment and displayed on the result page.

## Embedding configuration

DeepSeek chat models do not provide embeddings. Configure a separate OpenAI-compatible embedding
service in `backend/.env`:

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

## Build or refresh the index

Run from the `backend` directory:

```bash
python -m app.scripts.reindex_rag
```

The Chroma directory is ignored by Git. On the server, either rebuild it from the checked-in
corpus or copy the generated directory to the same project-relative path.

## Evaluation

Maintain labelled `blind spot -> expected source` pairs and report Recall@5, source coverage,
and the percentage of plans whose critical or major gaps have at least one retrieved source.
