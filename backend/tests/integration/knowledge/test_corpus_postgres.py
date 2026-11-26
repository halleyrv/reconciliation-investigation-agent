import dataclasses
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from recon.knowledge.adapters.inbound.ingest_corpus import run
from recon.knowledge.adapters.outbound.fake_models import HashEmbeddings
from recon.knowledge.adapters.outbound.sql import (
    VECTOR_SEARCH,
    SqlChunkSearch,
    SqlDocumentRepository,
)
from recon.knowledge.application.ingest_corpus import IngestCorpus
from recon.knowledge.domain.document import Document, DocumentKind
from recon.shared_kernel.ports import UuidIdGenerator
from tests.integration.conftest import SAMPLE

OCT = date(2026, 10, 1)
REFUNDS = (
    "# Refund Limits\n\nRefund window: 5 calendar days.\n\n"
    "## Repeats\n\nA second refund of the same payment is not allowed.\n"
)
FEES = "# Fee Schedule\n\nGateway fees are charged per transaction.\n"
EMBEDDINGS = HashEmbeddings(dimension=384)  # VECTOR(384), ADR-0023


def _document(key: str, content: str, version: int = 1) -> Document:
    first = Document.first(
        id=uuid.uuid4(), key=key, kind=DocumentKind.POLICY, content=content, effective_from=OCT
    )
    return dataclasses.replace(first, version=version)


def _add(repository: SqlDocumentRepository, document: Document) -> None:
    vectors = EMBEDDINGS.embed_passages([c.content for c in document.chunks])
    repository.add(document, EMBEDDINGS.model, vectors)


def test_a_stored_document_reads_back_whole_and_latest_is_its_highest_version(
    engine: Engine,
) -> None:
    repository = SqlDocumentRepository(engine)
    v1, v2 = _document("refund_limits", REFUNDS), _document("refund_limits", FEES, version=2)
    _add(repository, v1)
    _add(repository, v2)

    assert repository.latest("refund_limits") == v2
    assert repository.latest("dispute_handling") is None


def test_the_database_rejects_a_second_document_with_the_same_key_and_version(
    engine: Engine,
) -> None:
    repository = SqlDocumentRepository(engine)
    _add(repository, _document("refund_limits", REFUNDS))

    with pytest.raises(IntegrityError, match="documents_key_version_key"):
        _add(repository, _document("refund_limits", FEES))


def _stored(engine: Engine) -> tuple[SqlDocumentRepository, Document, Document]:
    repository = SqlDocumentRepository(engine)
    old, fees = _document("refund_limits", FEES), _document("fee_schedule", FEES + "\nPer day.\n")
    current = _document("refund_limits", REFUNDS, version=2)
    for document in (old, fees, current):
        _add(repository, document)
    return repository, current, fees


def _chunk_ids(engine: Engine, document: Document) -> list[uuid.UUID]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id FROM knowledge.document_chunks WHERE document_id = :d ORDER BY ordinal"
            ),
            {"d": document.id},
        )
        return [row.id for row in rows]


def test_full_text_search_ranks_matching_chunks_of_current_versions_only(engine: Engine) -> None:
    _, current, _ = _stored(engine)

    hits = SqlChunkSearch(engine).full_text("Is a second refunded payment allowed?", limit=10)

    # Chunk 1 shares four stemmed terms, chunk 0 only "refund"; the old version of
    # refund_limits shares none.
    assert [(h.document_key, h.version, h.ordinal) for h in hits] == [
        ("refund_limits", 2, 1),
        ("refund_limits", 2, 0),
    ]
    assert [h.chunk_id for h in hits] == _chunk_ids(engine, current)[::-1]
    assert {h.document_id for h in hits} == {current.id}
    assert hits[0].score > hits[1].score > 0


def test_full_text_search_without_a_matching_term_finds_nothing(engine: Engine) -> None:
    _stored(engine)
    assert SqlChunkSearch(engine).full_text("chargeback evidence deadline", limit=10) == []


def test_vector_search_ranks_by_cosine_similarity_within_the_query_model(engine: Engine) -> None:
    _, current, fees = _stored(engine)
    query = EMBEDDINGS.embed_query(current.chunks[1].content)

    hits = SqlChunkSearch(engine).vector(query, EMBEDDINGS.model, limit=2)

    assert (hits[0].document_key, hits[0].version, hits[0].ordinal) == ("refund_limits", 2, 1)
    assert hits[0].score == pytest.approx(1.0)
    assert len(hits) == 2 and hits[0].score > hits[1].score
    assert {h.document_id for h in hits} <= {current.id, fees.id}  # never the old version
    assert SqlChunkSearch(engine).vector(query, "another-model", limit=2) == []


def test_the_ingest_command_stores_the_corpus_once_and_reports_each_document(
    engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    def ingest() -> IngestCorpus:
        return IngestCorpus(SqlDocumentRepository(engine), EMBEDDINGS, UuidIdGenerator())

    policies = SAMPLE / "policies"
    argv = [str(policies), "--effective-from", "2026-10-01"]

    assert run(argv, ingest) == 0
    keys = sorted(p.stem for p in policies.glob("*.md"))
    assert capsys.readouterr().out == "".join(f"{k}: version 1, stored\n" for k in keys)

    assert run(argv, ingest) == 0
    assert capsys.readouterr().out == "".join(f"{k}: version 1, unchanged\n" for k in keys)
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT key, version, effective_from, embedding_model FROM knowledge.documents")
        )
        assert sorted(tuple(r) for r in stored) == [(k, 1, OCT, "fake-hash") for k in keys]


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda tmp: tmp / "missing", "no .md documents in"),
        (lambda tmp: tmp, "no .md documents in"),
        (
            lambda tmp: (tmp / "bad.md").write_text("No heading.\n") and tmp,
            "bad: a document starts",
        ),
    ],
)
def test_the_ingest_command_stores_nothing_from_a_corpus_it_cannot_read(
    engine: Engine,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make: object,
    message: str,
) -> None:
    directory = make(tmp_path)  # type: ignore[operator]

    def ingest() -> IngestCorpus:
        return IngestCorpus(SqlDocumentRepository(engine), EMBEDDINGS, UuidIdGenerator())

    assert run([str(directory)], ingest) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("recon-ingest-corpus: nothing ingested: ") and message in err
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM knowledge.documents")).scalar() == 0


def test_vector_search_is_served_by_the_hnsw_index(engine: Engine) -> None:
    _stored(engine)
    query = "[" + ",".join(["0.1"] * 384) + "]"
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = connection.execute(
            text(f"EXPLAIN {VECTOR_SEARCH.text}"),
            {"query": query, "model": "fake-hash", "limit": 2, "kinds": None, "keys": None},
        ).scalars()
        assert "document_chunks_embedding_idx" in "\n".join(plan)


def test_an_infrastructure_failure_while_ingesting_exits_3_and_says_what_stays_stored(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def ingest() -> IngestCorpus:
        raise ConnectionError("model download failed")

    assert run([str(SAMPLE / "policies")], ingest) == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert err == (
        "recon-ingest-corpus: ingest failed: model download failed;"
        " documents stored before the failure stay, re-run to finish\n"
    )
