"""Hybrid retrieval: full text and vector search fused by Reciprocal Rank Fusion, then the
fused top reranked by a cross-encoder (ADR-0023).

RRF fuses by rank, not by score: a ts_rank_cd and a cosine similarity are not on one scale,
so adding or normalizing them would weight one search by accident (Cormack et al., 2009)."""

import uuid
from dataclasses import dataclass

from recon.knowledge.application.ports import (
    NO_FILTERS,
    ChunkHit,
    ChunkSearch,
    EmbeddingProvider,
    Reranker,
    RetrievalFilters,
)

RRF_K = 60  # the constant of the RRF paper; it damps the weight of the very first ranks
FIRST_STAGE_DEPTH = 20  # hits each search contributes to the fusion
RERANK_DEPTH = 10  # fused candidates the cross-encoder scores (ADR-0023)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A retrieved chunk, with its source (document version, section) and how it ranked."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_key: str
    version: int
    ordinal: int
    section: str
    content: str
    full_text_rank: int | None  # 1-based rank in each search; None when that search missed it
    vector_rank: int | None
    fused_score: float  # sum of 1 / (RRF_K + rank) over the searches that found the chunk
    rerank_score: float  # the cross-encoder's; the results are in its order


class HybridRetrieval:
    def __init__(self, search: ChunkSearch, embeddings: EmbeddingProvider, reranker: Reranker):
        self._search = search
        self._embeddings = embeddings
        self._reranker = reranker

    def retrieve(
        self, query: str, filters: RetrievalFilters = NO_FILTERS, limit: int = 5
    ) -> list[RetrievedChunk]:
        """At most ``limit`` chunks, most relevant first; none when no search matches."""
        if not query.strip():
            raise ValueError("blank query")
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        full_text = self._search.full_text(query, FIRST_STAGE_DEPTH, filters)
        vector = self._search.vector(
            self._embeddings.embed_query(query), self._embeddings.model, FIRST_STAGE_DEPTH, filters
        )
        text_ranks = {h.chunk_id: rank for rank, h in enumerate(full_text, 1)}
        vector_ranks = {h.chunk_id: rank for rank, h in enumerate(vector, 1)}
        hits: dict[uuid.UUID, ChunkHit] = {h.chunk_id: h for h in (*vector, *full_text)}

        def fused(chunk_id: uuid.UUID) -> float:
            ranks = (text_ranks.get(chunk_id), vector_ranks.get(chunk_id))
            return sum(1 / (RRF_K + r) for r in ranks if r is not None)

        # Ties keep a stable order by document and chunk, so equal inputs give equal outputs.
        candidates = sorted(
            hits.values(), key=lambda h: (-fused(h.chunk_id), h.document_key, h.ordinal)
        )[:RERANK_DEPTH]
        if not candidates:
            return []
        scores = self._reranker.score(query, [h.content for h in candidates])
        order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))[:limit]
        return [
            RetrievedChunk(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                document_key=h.document_key,
                version=h.version,
                ordinal=h.ordinal,
                section=h.section,
                content=h.content,
                full_text_rank=text_ranks.get(h.chunk_id),
                vector_rank=vector_ranks.get(h.chunk_id),
                fused_score=fused(h.chunk_id),
                rerank_score=scores[i],
            )
            for i in order
            for h in (candidates[i],)
        ]
