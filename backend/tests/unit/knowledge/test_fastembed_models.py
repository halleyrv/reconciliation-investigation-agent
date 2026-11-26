"""Real local models. fastembed has no wheel for Intel macOS with Python 3.14 (D4), so these run
in Linux (CI, the ``models`` Compose service) and are skipped elsewhere."""

import pytest

pytest.importorskip("fastembed", reason="fastembed is not installed on this platform (D4)")

from recon.knowledge.adapters.outbound.fastembed_models import (
    FastembedEmbeddings,
    FastembedReranker,
)
from recon.knowledge.application.ranking import rank_by_similarity, rerank

PASSAGES = [
    "Refund window: 5 calendar days after the payment is captured.",
    "Gateway fees are charged per transaction and settled monthly.",
]
QUERY = "How long after capture can a payment be refunded?"


def test_embeddings_have_the_declared_dimension_and_rank_the_relevant_passage_first() -> None:
    model = FastembedEmbeddings("BAAI/bge-small-en-v1.5")
    vectors = model.embed_passages(PASSAGES)
    assert model.dimension == 384
    assert all(len(v) == 384 for v in vectors)
    ranking = rank_by_similarity(
        model.embed_query(QUERY), [(("p", 0), vectors[0]), (("p", 1), vectors[1])]
    )
    assert ranking[0] == ("p", 0)


def test_reranker_scores_the_relevant_passage_above_the_other() -> None:
    model = FastembedReranker("Xenova/ms-marco-MiniLM-L-6-v2")
    candidates = [(("p", 1), PASSAGES[1]), (("p", 0), PASSAGES[0])]
    assert rerank(model, QUERY, candidates) == [("p", 0), ("p", 1)]


def test_an_unknown_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="not supported"):
        FastembedEmbeddings("no/such-model")
