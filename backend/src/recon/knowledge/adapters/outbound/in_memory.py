"""In-memory document repository for application tests (port inventory)."""

import uuid
from collections.abc import Sequence

from recon.knowledge.application.ports import Vector
from recon.knowledge.domain.document import Document


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: list[Document] = []  # in insertion order
        self.embeddings: dict[uuid.UUID, tuple[str, list[Vector]]] = {}

    def latest(self, key: str) -> Document | None:
        versions = [d for d in self.documents if d.key == key]
        return max(versions, key=lambda d: d.version, default=None)

    def add(self, document: Document, embedding_model: str, embeddings: Sequence[Vector]) -> None:
        if len(embeddings) != len(document.chunks):
            raise ValueError("one embedding per chunk")
        self.documents.append(document)
        self.embeddings[document.id] = (embedding_model, list(embeddings))
