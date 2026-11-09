# ADR-0006: Local embedding model and reranker

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** docs/architecture/data-model.md (`knowledge`)

## Context

Hybrid retrieval needs embeddings (stored in `VECTOR(N)`) and a reranker. The embedding dimension `N` is fixed in the schema. Retrieval evaluations must be reproducible, and the corpus is synthetic and small.

## Decision

Use locally run open models for embeddings and cross-encoder reranking, behind the `EmbeddingProvider` and `Reranker` ports. The specific models are chosen in Phase 3 (hybrid RAG) by comparing them on the retrieval evaluation set, and that choice fixes `N`.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Hosted embedding/rerank APIs | Per-call cost, network dependency in tests and evaluations, and results can shift when the provider updates a model |
| No reranker | Weaker precision on top results, which is exactly what evidence attribution depends on |

## Consequences

- **Positive:** Free, offline, reproducible evaluations.
- **Negative:** Larger Docker images and slower CPU inference. Possibly lower quality than top hosted models.
- **Follow-ups:** `knowledge.documents.embedding_model` records the model. Changing the model requires a re-embedding job and a new ADR.
