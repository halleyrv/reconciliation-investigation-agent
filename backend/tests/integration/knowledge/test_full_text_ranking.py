from sqlalchemy import Engine

from recon.knowledge.adapters.outbound.full_text_ranking import rank_by_full_text

CHUNKS = [
    (("refund_limits", 0), "Refund window: 5 calendar days. A refund is allowed once."),
    (("fee_schedule", 0), "Gateway fees are charged per transaction."),
    (("refund_limits", 1), "A second refund of the same payment is not allowed."),
]


def test_full_text_ranks_matching_chunks_by_relevance_and_drops_the_rest(engine: Engine) -> None:
    # "refunded" stems to "refund"; any query term is enough to match (OR semantics).
    ranking = rank_by_full_text(engine, "How many days can a payment be refunded?", CHUNKS)
    assert ranking == [("refund_limits", 0), ("refund_limits", 1)]


def test_full_text_returns_nothing_when_no_term_matches(engine: Engine) -> None:
    assert rank_by_full_text(engine, "chargeback evidence deadline", CHUNKS) == []
