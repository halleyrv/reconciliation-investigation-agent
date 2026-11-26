from datetime import date

import pytest

from recon.knowledge.adapters.outbound.fake_models import HashEmbeddings
from recon.knowledge.adapters.outbound.in_memory import InMemoryDocumentRepository
from recon.knowledge.application.ingest_corpus import IngestCorpus, Ingested
from recon.knowledge.domain.document import DocumentKind, InvalidDocument
from recon.shared_kernel.ports import SequenceIdGenerator

OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)
REFUNDS = "# Refund Limits\n\nRefund window: 5 calendar days.\n"
FEES = "# Fee Schedule\n\nGateway fees are charged per transaction.\n"


def _ingest(repository: InMemoryDocumentRepository) -> IngestCorpus:
    return IngestCorpus(repository, HashEmbeddings(), SequenceIdGenerator())


def test_a_new_document_is_stored_as_version_1_with_one_embedding_per_chunk() -> None:
    repository = InMemoryDocumentRepository()

    result = _ingest(repository)([("refund_limits", REFUNDS)], DocumentKind.POLICY, OCT)

    assert result == [Ingested("refund_limits", 1, changed=True)]
    document = repository.latest("refund_limits")
    assert document is not None
    assert (document.version, document.title, document.effective_from) == (1, "Refund Limits", OCT)
    model, vectors = repository.embeddings[document.id]
    assert model == "fake-hash"
    assert vectors == HashEmbeddings().embed_passages([c.content for c in document.chunks])


def test_unchanged_content_is_not_stored_again() -> None:
    repository = InMemoryDocumentRepository()
    _ingest(repository)([("refund_limits", REFUNDS)], DocumentKind.POLICY, OCT)

    result = _ingest(repository)([("refund_limits", REFUNDS)], DocumentKind.POLICY, NOV)

    assert result == [Ingested("refund_limits", 1, changed=False)]
    assert [d.version for d in repository.documents] == [1]


def test_changed_content_becomes_the_next_version_and_keeps_the_previous_one() -> None:
    repository = InMemoryDocumentRepository()
    _ingest(repository)(
        [("refund_limits", REFUNDS), ("fee_schedule", FEES)], DocumentKind.POLICY, OCT
    )

    revised = REFUNDS.replace("5 calendar", "7 calendar")
    result = _ingest(repository)(
        [("refund_limits", revised), ("fee_schedule", FEES)], DocumentKind.POLICY, NOV
    )

    assert result == [Ingested("refund_limits", 2, True), Ingested("fee_schedule", 1, False)]
    latest = repository.latest("refund_limits")
    assert latest is not None
    assert (latest.version, latest.content, latest.effective_from) == (2, revised, NOV)
    assert [(d.key, d.version) for d in repository.documents] == [
        ("refund_limits", 1),
        ("fee_schedule", 1),
        ("refund_limits", 2),
    ]


def test_an_invalid_document_stores_nothing_from_the_corpus() -> None:
    repository = InMemoryDocumentRepository()

    with pytest.raises(InvalidDocument, match="untitled: a document starts with a '# ' title"):
        _ingest(repository)(
            [("refund_limits", REFUNDS), ("untitled", "No heading here.\n")],
            DocumentKind.POLICY,
            OCT,
        )
    assert repository.documents == []
