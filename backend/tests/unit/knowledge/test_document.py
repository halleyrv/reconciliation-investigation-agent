import dataclasses
import hashlib
import uuid
from datetime import date

import pytest

from recon.knowledge.domain.document import (
    Document,
    DocumentKind,
    InvalidDocument,
    chunk_markdown,
)

POLICY = (
    "# Settlement and Cut-off Policy\n\n"
    "Each gateway settles one batch per calendar day.\n\n"
    "Settlement lag: 2 business days\n\n"
    "## Payouts\n\n"
    "Each batch is paid out as exactly one bank credit.\n\n"
    "| Gateway | Lag |\n"
    "|---------|-----|\n"
    "| gateway_a | 2 |\n"
)
DOC_ID = uuid.UUID(int=1)
EFFECTIVE = date(2026, 10, 1)


def _first(content: str = POLICY, max_chars: int = 1000) -> Document:
    return Document.first(
        id=DOC_ID,
        key="settlement_policy",
        kind=DocumentKind.POLICY,
        content=content,
        effective_from=EFFECTIVE,
        max_chunk_chars=max_chars,
    )


def test_a_first_document_is_version_1_titled_by_its_heading_and_hashed() -> None:
    document = _first()
    assert document.version == 1
    assert document.title == "Settlement and Cut-off Policy"
    assert document.content_sha256 == hashlib.sha256(POLICY.encode()).hexdigest()
    assert document.key == "settlement_policy"
    assert document.effective_from == EFFECTIVE


def test_chunks_follow_sections_and_each_is_the_exact_span_of_the_document() -> None:
    chunks = _first().chunks
    assert [c.ordinal for c in chunks] == [0, 1]
    assert [c.section for c in chunks] == ["Settlement and Cut-off Policy", "Payouts"]
    for chunk in chunks:
        assert POLICY[chunk.start : chunk.end] == chunk.content
    assert chunks[0].content == (
        "# Settlement and Cut-off Policy\n\n"
        "Each gateway settles one batch per calendar day.\n\n"
        "Settlement lag: 2 business days"
    )
    assert chunks[1].content.endswith("| gateway_a | 2 |")


def test_a_section_longer_than_the_limit_splits_between_blocks_never_inside_one() -> None:
    chunks = chunk_markdown(POLICY, max_chars=60)
    assert [c.section for c in chunks] == [
        "Settlement and Cut-off Policy",
        "Settlement and Cut-off Policy",
        "Payouts",
        "Payouts",
    ]
    assert chunks[1].content == "Settlement lag: 2 business days"
    table = "| Gateway | Lag |\n|---------|-----|\n| gateway_a | 2 |"
    assert chunks[3].content == table  # a block longer than the limit stays whole


def test_revising_changed_content_makes_the_next_version_of_the_same_document() -> None:
    first = _first()
    changed = POLICY.replace("2 business days", "3 business days")
    second = first.revise(id=uuid.UUID(int=2), content=changed, effective_from=date(2026, 11, 1))
    assert second is not None
    assert (second.key, second.kind, second.version) == (first.key, first.kind, 2)
    assert second.content_sha256 == hashlib.sha256(changed.encode()).hexdigest()
    assert "Settlement lag: 3 business days" in second.chunks[0].content


def test_revising_with_the_same_content_makes_no_new_version() -> None:
    first = _first()
    assert first.revise(id=uuid.UUID(int=2), content=POLICY, effective_from=EFFECTIVE) is None


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "a document needs content"),
        ("   \n", "a document needs content"),
        ("No heading here.\n", "a document starts with a '# ' title"),
    ],
)
def test_a_document_without_content_or_title_is_rejected(content: str, message: str) -> None:
    with pytest.raises(InvalidDocument, match=message):
        _first(content)


def test_a_document_rejects_chunks_that_break_its_invariants() -> None:
    document = _first()
    gap = (document.chunks[0], dataclasses.replace(document.chunks[1], ordinal=2))
    with pytest.raises(InvalidDocument, match="chunk ordinals are contiguous from 0"):
        dataclasses.replace(document, chunks=gap)
    edited = (dataclasses.replace(document.chunks[0], content="edited"), document.chunks[1])
    with pytest.raises(InvalidDocument, match="chunk 0 is not the document text at its span"):
        dataclasses.replace(document, chunks=edited)
    with pytest.raises(InvalidDocument, match="content hash does not match"):
        dataclasses.replace(document, content_sha256="0" * 64)
    with pytest.raises(InvalidDocument, match="a document version starts at 1"):
        dataclasses.replace(document, version=0)
