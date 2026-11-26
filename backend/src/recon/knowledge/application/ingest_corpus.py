"""Ingests a corpus of documents: a new key becomes version 1, a changed text the next version,
an unchanged text nothing. Every chunk of a stored version is embedded with one model."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from recon.knowledge.application.ports import DocumentRepository, EmbeddingProvider
from recon.knowledge.domain.document import Document, DocumentKind, InvalidDocument
from recon.shared_kernel.ports import IdGenerator


@dataclass(frozen=True, slots=True)
class Ingested:
    key: str
    version: int  # the version now current
    changed: bool  # False when the text equals the current version


class IngestCorpus:
    def __init__(
        self, documents: DocumentRepository, embeddings: EmbeddingProvider, ids: IdGenerator
    ) -> None:
        self._documents = documents
        self._embeddings = embeddings
        self._ids = ids

    def __call__(
        self, texts: Sequence[tuple[str, str]], kind: DocumentKind, effective_from: date
    ) -> list[Ingested]:
        """``texts`` are (key, content) pairs. Every text is validated before any is stored,
        so an invalid document stores nothing from the corpus."""
        planned = [self._next_version(key, content, kind, effective_from) for key, content in texts]
        for result, document in planned:
            if result.changed:
                vectors = self._embeddings.embed_passages([c.content for c in document.chunks])
                self._documents.add(document, self._embeddings.model, vectors)
        return [result for result, _ in planned]

    def _next_version(
        self, key: str, content: str, kind: DocumentKind, effective_from: date
    ) -> tuple[Ingested, Document]:
        """The document now current, and whether it is new."""
        current = self._documents.latest(key)
        try:
            if current is None:
                document = Document.first(
                    id=self._ids.new(),
                    key=key,
                    kind=kind,
                    content=content,
                    effective_from=effective_from,
                )
                return Ingested(key, 1, changed=True), document
            revised = current.revise(
                id=self._ids.new(), content=content, effective_from=effective_from
            )
        except InvalidDocument as exc:
            raise InvalidDocument(f"{key}: {exc}") from exc
        if revised is None:
            return Ingested(key, current.version, changed=False), current
        return Ingested(key, revised.version, changed=True), revised
