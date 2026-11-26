import math

import pytest

from recon.knowledge.adapters.outbound.fake_models import HashEmbeddings, IdentityReranker
from recon.knowledge.application.ranking import rank_by_similarity, rerank

A, B, C = ("a", 0), ("a", 1), ("b", 0)


def test_rank_by_similarity_orders_chunks_by_cosine_similarity_to_the_query() -> None:
    vectors = [(A, (0.0, 1.0)), (B, (1.0, 0.0)), (C, (1.0, 1.0))]
    # Cosine ignores the length: (2, 0.1) points almost exactly along B.
    assert rank_by_similarity((2.0, 0.1), vectors) == [B, C, A]


def test_rank_by_similarity_breaks_ties_by_chunk_reference() -> None:
    vectors = [(C, (1.0, 0.0)), (A, (1.0, 0.0)), (B, (1.0, 0.0))]
    assert rank_by_similarity((1.0, 0.0), vectors) == [A, B, C]


def test_rank_by_similarity_rejects_vectors_of_another_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        rank_by_similarity((1.0, 0.0), [(A, (1.0, 0.0, 0.0))])


class _LengthReranker:
    model = "length"

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(len(t)) for t in texts]


def test_rerank_orders_candidates_by_the_reranker_score() -> None:
    candidates = [(A, "aa"), (B, "aaaa"), (C, "a")]
    assert rerank(_LengthReranker(), "q", candidates) == [B, A, C]


def test_rerank_of_no_candidates_is_empty() -> None:
    assert rerank(_LengthReranker(), "q", []) == []


def test_hash_embeddings_are_deterministic_unit_vectors_of_the_declared_dimension() -> None:
    fake = HashEmbeddings(dimension=8)
    [first, second] = fake.embed_passages(["refund window", "settlement"])
    assert len(first) == 8
    assert math.isclose(math.fsum(x * x for x in first), 1.0)
    assert fake.embed_query("refund window") == first
    assert first != second


def test_identity_reranker_keeps_the_candidate_order() -> None:
    candidates = [(C, "z"), (A, "y"), (B, "x")]
    assert rerank(IdentityReranker(), "q", candidates) == [C, A, B]
