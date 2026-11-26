import dataclasses
import uuid
from datetime import date

from sqlalchemy import Engine, text

from recon.knowledge.adapters.outbound.fake_models import HashEmbeddings, IdentityReranker
from recon.knowledge.adapters.outbound.sql import SqlChunkSearch, SqlDocumentRepository
from recon.knowledge.api import HybridRetrieval, RetrievalFilters
from recon.knowledge.domain.document import Document, DocumentKind

EMBEDDINGS = HashEmbeddings(dimension=384)  # VECTOR(384), ADR-0023
REFUNDS = (
    "# Refund Limits\n\nRefund window: 5 calendar days.\n\n"
    "## Repeats\n\nA second refund of the same payment is not allowed.\n"
)
FEES = "# Fee Schedule\n\nGateway fees are charged per refund and per payment.\n"
CONTRACT = "# Merchant Agreement\n\nA refund of a payment follows the merchant agreement.\n"


def _store(engine: Engine, key: str, content: str, kind: DocumentKind, version: int) -> Document:
    first = Document.first(
        id=uuid.uuid4(), key=key, kind=kind, content=content, effective_from=date(2026, 10, 1)
    )
    document = dataclasses.replace(first, version=version)
    vectors = EMBEDDINGS.embed_passages([c.content for c in document.chunks])
    SqlDocumentRepository(engine).add(document, EMBEDDINGS.model, vectors)
    return document


def _retrieval(engine: Engine) -> HybridRetrieval:
    return HybridRetrieval(SqlChunkSearch(engine), EMBEDDINGS, IdentityReranker())


def test_retrieve_returns_chunks_of_current_versions_with_their_attribution_and_scores(
    engine: Engine,
) -> None:
    old = _store(engine, "refund_limits", FEES, DocumentKind.POLICY, version=1)
    current = _store(engine, "refund_limits", REFUNDS, DocumentKind.POLICY, version=2)
    _store(engine, "fee_schedule", FEES, DocumentKind.POLICY, version=1)
    repeats = current.chunks[1]

    results = _retrieval(engine).retrieve(repeats.content, limit=10)

    # The query is the chunk's own text: first in full text and, with cosine 1.0, in vector.
    top = results[0]
    assert (top.document_key, top.version, top.ordinal) == ("refund_limits", 2, 1)
    assert (top.document_id, top.section, top.content) == (current.id, "Repeats", repeats.content)
    assert (top.full_text_rank, top.vector_rank) == (1, 1)
    with engine.connect() as connection:
        stored_id = connection.execute(
            text("SELECT id FROM knowledge.document_chunks WHERE document_id = :d AND ordinal = 1"),
            {"d": current.id},
        ).scalar_one()
    assert top.chunk_id == stored_id
    assert old.id not in {r.document_id for r in results}
    assert [r.fused_score for r in results] == sorted(
        (r.fused_score for r in results), reverse=True
    )


def test_retrieve_keeps_only_the_documents_and_kinds_the_filters_name(engine: Engine) -> None:
    _store(engine, "refund_limits", REFUNDS, DocumentKind.POLICY, version=1)
    _store(engine, "fee_schedule", FEES, DocumentKind.POLICY, version=1)
    _store(engine, "merchant_agreement", CONTRACT, DocumentKind.CONTRACT, version=1)
    query = "refund of a payment"

    by_key = _retrieval(engine).retrieve(
        query, RetrievalFilters(document_keys=frozenset({"fee_schedule"})), limit=10
    )
    by_kind = _retrieval(engine).retrieve(
        query, RetrievalFilters(kinds=frozenset({DocumentKind.CONTRACT})), limit=10
    )
    unfiltered = _retrieval(engine).retrieve(query, limit=10)

    assert by_key and {r.document_key for r in by_key} == {"fee_schedule"}
    assert by_kind and {r.document_key for r in by_kind} == {"merchant_agreement"}
    assert {r.document_key for r in unfiltered} == {
        "refund_limits",
        "fee_schedule",
        "merchant_agreement",
    }
