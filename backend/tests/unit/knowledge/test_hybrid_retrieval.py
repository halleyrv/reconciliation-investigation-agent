import uuid

import pytest

from recon.knowledge.adapters.outbound.fake_models import HashEmbeddings, IdentityReranker
from recon.knowledge.api import (
    RERANK_DEPTH,
    RRF_K,
    ChunkHit,
    HybridRetrieval,
    RetrievalFilters,
    RetrievedChunk,
)
from recon.knowledge.application.ports import Vector
from recon.knowledge.domain.document import DocumentKind

EMBEDDINGS = HashEmbeddings()


def _hit(key: str, ordinal: int, score: float = 0.5) -> ChunkHit:
    return ChunkHit(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, f"{key}/{ordinal}"),
        document_id=uuid.uuid5(uuid.NAMESPACE_OID, key),
        document_key=key,
        version=2,
        ordinal=ordinal,
        section="Limits",
        content=f"{key} chunk {ordinal}",
        score=score,
    )


class _ScriptedSearch:
    """Returns fixed hits and records what each search was asked."""

    def __init__(self, full_text: list[ChunkHit], vector: list[ChunkHit]) -> None:
        self._full_text, self._vector = full_text, vector
        self.calls: list[tuple[object, ...]] = []

    def full_text(self, query: str, limit: int, filters: RetrievalFilters) -> list[ChunkHit]:
        self.calls.append(("full_text", query, limit, filters))
        return self._full_text[:limit]

    def vector(
        self, query: Vector, model: str, limit: int, filters: RetrievalFilters
    ) -> list[ChunkHit]:
        self.calls.append(("vector", query, model, limit, filters))
        return self._vector[:limit]


class _ByContentReranker:
    """Scores the texts by a fixed table, to reorder the fused candidates deterministically."""

    model = "scripted"

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores
        self.seen: list[list[str]] = []

    def score(self, query: str, texts: list[str]) -> list[float]:
        self.seen.append(texts)
        return [self._scores.get(t, 0.0) for t in texts]


A, B, C, D = _hit("refund_limits", 0), _hit("refund_limits", 1), _hit("fees", 0), _hit("fees", 1)


def _keys(results: list[RetrievedChunk]) -> list[tuple[str, int]]:
    return [(r.document_key, r.ordinal) for r in results]


def test_fusion_ranks_a_chunk_both_searches_found_above_chunks_only_one_found() -> None:
    # B is second in both lists; A and C are first in only one each.
    search = _ScriptedSearch(full_text=[A, B], vector=[C, B])
    retrieval = HybridRetrieval(search, EMBEDDINGS, IdentityReranker())

    results = retrieval.retrieve("second refund", limit=3)

    # A and C tie at one first rank each; the tie goes by document key, then ordinal.
    assert _keys(results) == [("refund_limits", 1), ("fees", 0), ("refund_limits", 0)]
    both, only_vector, only_text = results
    assert both.fused_score == pytest.approx(2 / (RRF_K + 2))
    assert (both.full_text_rank, both.vector_rank) == (2, 2)
    assert only_text.fused_score == pytest.approx(1 / (RRF_K + 1))
    assert (only_text.full_text_rank, only_text.vector_rank) == (1, None)
    assert (only_vector.full_text_rank, only_vector.vector_rank) == (None, 1)


def test_the_reranker_orders_the_fused_candidates_and_its_score_is_returned() -> None:
    search = _ScriptedSearch(full_text=[A, B, C], vector=[A, B, C])
    reranker = _ByContentReranker({C.content: 3.0, A.content: 1.0, B.content: 2.0})

    results = HybridRetrieval(search, EMBEDDINGS, reranker).retrieve("fees", limit=2)

    assert reranker.seen == [[A.content, B.content, C.content]]  # in fused order
    assert _keys(results) == [("fees", 0), ("refund_limits", 1)]
    assert [r.rerank_score for r in results] == [3.0, 2.0]
    top = results[0]
    assert (top.chunk_id, top.document_id, top.version, top.section, top.content) == (
        C.chunk_id,
        C.document_id,
        2,
        "Limits",
        "fees chunk 0",
    )


def test_only_the_fused_top_candidates_are_reranked() -> None:
    hits = [_hit("corpus", i) for i in range(RERANK_DEPTH + 5)]
    search = _ScriptedSearch(full_text=hits, vector=hits)
    reranker = _ByContentReranker({hits[-1].content: 99.0})

    results = HybridRetrieval(search, EMBEDDINGS, reranker).retrieve("q", limit=RERANK_DEPTH)

    assert len(reranker.seen[0]) == RERANK_DEPTH
    assert hits[-1].chunk_id not in {r.chunk_id for r in results}


def test_both_searches_receive_the_filters_and_the_vector_search_the_query_model() -> None:
    search = _ScriptedSearch(full_text=[], vector=[])
    filters = RetrievalFilters(
        kinds=frozenset({DocumentKind.POLICY}), document_keys=frozenset({"fees"})
    )

    assert HybridRetrieval(search, EMBEDDINGS, IdentityReranker()).retrieve("q", filters) == []

    (_, text, _, text_filters), (_, vector, model, _, vector_filters) = search.calls
    assert text == "q" and text_filters == filters
    assert vector == EMBEDDINGS.embed_query("q") and model == EMBEDDINGS.model
    assert vector_filters == filters


def test_nothing_found_returns_nothing_without_calling_the_reranker() -> None:
    reranker = _ByContentReranker({})
    retrieval = HybridRetrieval(_ScriptedSearch([], []), EMBEDDINGS, reranker)
    assert retrieval.retrieve("chargeback") == []
    assert reranker.seen == []


@pytest.mark.parametrize(("query", "limit"), [("  ", 5), ("q", 0)])
def test_a_blank_query_or_a_limit_below_one_is_rejected(query: str, limit: int) -> None:
    retrieval = HybridRetrieval(_ScriptedSearch([A], [A]), EMBEDDINGS, IdentityReranker())
    with pytest.raises(ValueError, match=r"blank query|limit"):
        retrieval.retrieve(query, limit=limit)
