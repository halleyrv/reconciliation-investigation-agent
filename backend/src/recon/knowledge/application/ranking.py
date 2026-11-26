"""Rank chunks against a query: by embedding similarity, then optionally by a reranker."""

import math
from collections.abc import Sequence

from recon.knowledge.application.ports import Reranker, Vector
from recon.knowledge.application.retrieval_evaluation import ChunkRef


def _cosine(a: Vector, b: Vector) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dimension {len(b)} differs from the query's {len(a)}")
    norm = math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(y * y for y in b))
    return math.fsum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def rank_by_similarity(query: Vector, chunks: Sequence[tuple[ChunkRef, Vector]]) -> list[ChunkRef]:
    """Most similar first; equal scores keep a stable order by chunk reference."""
    scored = sorted((-_cosine(query, vector), ref) for ref, vector in chunks)
    return [ref for _, ref in scored]


def rerank(
    reranker: Reranker, query: str, candidates: Sequence[tuple[ChunkRef, str]]
) -> list[ChunkRef]:
    if not candidates:
        return []
    scores = reranker.score(query, [text for _, text in candidates])
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    return [candidates[i][0] for i in order]
