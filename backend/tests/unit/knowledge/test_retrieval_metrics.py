import math

import pytest

from recon.knowledge.application.retrieval_evaluation import (
    evaluate,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

A, B, C, X, Y = ("a", 0), ("b", 0), ("c", 0), ("x", 0), ("y", 0)


def test_recall_at_k_is_the_share_of_relevant_chunks_in_the_top_k() -> None:
    ranked = [A, X, B, Y]
    assert recall_at_k(ranked, frozenset({A, B, C}), k=2) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, frozenset({A, B, C}), k=4) == pytest.approx(2 / 3)


def test_reciprocal_rank_is_one_over_the_rank_of_the_first_relevant_chunk() -> None:
    assert reciprocal_rank([X, Y, A, B], frozenset({A, B})) == pytest.approx(1 / 3)
    assert reciprocal_rank([X, Y], frozenset({A})) == 0.0


def test_ndcg_discounts_a_relevant_chunk_by_its_rank_against_the_ideal_order() -> None:
    assert ndcg_at_k([X, A], frozenset({A}), k=2) == pytest.approx(1 / math.log2(3))
    assert ndcg_at_k([A, B, X], frozenset({A, B}), k=3) == pytest.approx(1.0)
    assert ndcg_at_k([X, Y], frozenset({A}), k=2) == 0.0
    # The ideal ranking can hold at most k relevant chunks.
    assert ndcg_at_k([A, X], frozenset({A, B, C}), k=1) == pytest.approx(1.0)


def test_evaluate_averages_every_metric_over_the_queries() -> None:
    score = evaluate([([A, X], frozenset({A})), ([X, B], frozenset({B}))], k=1)
    assert score.queries == 2
    assert score.recall_at_k == pytest.approx(0.5)
    assert score.mrr == pytest.approx((1 + 1 / 2) / 2)
    assert score.ndcg_at_k == pytest.approx(0.5)


@pytest.mark.parametrize("k", [0, -1])
def test_a_cutoff_below_one_is_rejected(k: int) -> None:
    with pytest.raises(ValueError, match="k must be at least 1"):
        recall_at_k([A], frozenset({A}), k=k)
    with pytest.raises(ValueError, match="k must be at least 1"):
        ndcg_at_k([A], frozenset({A}), k=k)


def test_a_query_without_relevant_chunks_cannot_be_scored() -> None:
    with pytest.raises(ValueError, match="a query needs at least one relevant chunk"):
        evaluate([([A], frozenset())], k=1)
