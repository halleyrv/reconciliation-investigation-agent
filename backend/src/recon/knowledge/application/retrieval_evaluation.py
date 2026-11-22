"""Retrieval evaluation: labeled queries and the metrics that score a ranking against them.

Labels name a passage of a document, not a chunk number, so one dataset scores every chunk
size: a chunk is relevant when it contains a labeled passage. Pure functions, no I/O.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from recon.knowledge.domain.document import Document

type ChunkRef = tuple[str, int]  # (document key, chunk ordinal)


class InvalidLabel(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RelevantPassage:
    document: str  # document key
    passage: str  # verbatim text of the document


@dataclass(frozen=True, slots=True)
class LabeledQuery:
    id: str
    query: str
    relevant: tuple[RelevantPassage, ...]

    def __post_init__(self) -> None:
        if not self.relevant:
            raise InvalidLabel(f"{self.id}: a query needs at least one relevant passage")
        for label in self.relevant:
            if not label.passage.strip():
                raise InvalidLabel(f"{self.id}: a passage needs text")
            # Chunks split only between blocks, so a passage inside one block is never split.
            if "\n\n" in label.passage:
                raise InvalidLabel(f"{self.id}: a passage stays in one block (no blank line)")


@dataclass(frozen=True, slots=True)
class RetrievalScore:
    queries: int
    recall_at_k: float
    mrr: float
    ndcg_at_k: float


def relevant_chunks(query: LabeledQuery, corpus: Mapping[str, Document]) -> frozenset[ChunkRef]:
    found: set[ChunkRef] = set()
    for label in query.relevant:
        document = corpus.get(label.document)
        if document is None:
            raise InvalidLabel(f"{query.id}: unknown document {label.document!r}")
        hits = {(document.key, c.ordinal) for c in document.chunks if label.passage in c.content}
        if not hits:
            raise InvalidLabel(f"{query.id}: passage not found in {label.document!r}")
        found |= hits
    return frozenset(found)


def _check_k(k: int) -> None:
    if k < 1:
        raise ValueError("k must be at least 1")


def recall_at_k(ranked: Sequence[ChunkRef], relevant: frozenset[ChunkRef], k: int) -> float:
    _check_k(k)
    return len(relevant.intersection(ranked[:k])) / len(relevant)


def reciprocal_rank(ranked: Sequence[ChunkRef], relevant: frozenset[ChunkRef]) -> float:
    return next((1 / rank for rank, ref in enumerate(ranked, 1) if ref in relevant), 0.0)


def ndcg_at_k(ranked: Sequence[ChunkRef], relevant: frozenset[ChunkRef], k: int) -> float:
    """Binary relevance: a relevant chunk at rank r adds 1 / log2(r + 1)."""
    _check_k(k)
    dcg = sum(1 / math.log2(rank + 1) for rank, ref in enumerate(ranked[:k], 1) if ref in relevant)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal


def evaluate(
    results: Iterable[tuple[Sequence[ChunkRef], frozenset[ChunkRef]]], k: int
) -> RetrievalScore:
    """Mean of each metric over (ranking, relevant chunks) pairs, one pair per query."""
    rows = list(results)
    if any(not relevant for _, relevant in rows):
        raise ValueError("a query needs at least one relevant chunk")
    count = len(rows)
    return RetrievalScore(
        queries=count,
        recall_at_k=sum(recall_at_k(r, rel, k) for r, rel in rows) / count,
        mrr=sum(reciprocal_rank(r, rel) for r, rel in rows) / count,
        ndcg_at_k=sum(ndcg_at_k(r, rel, k) for r, rel in rows) / count,
    )
