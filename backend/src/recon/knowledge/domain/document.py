"""Document: one version of a policy text with its chunks. A chunk is an exact span of the
text, so a quote attributed to a chunk can be checked against the document it came from."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# A block is a run of non-blank lines: a heading, a paragraph, a list or a table.
_BLOCK = re.compile(r"(?:^[ \t]*\S.*(?:\n|$))+", re.MULTILINE)
_HEADING = re.compile(r"#{1,6} ")
# shortcut: a fixed size for the first corpus, T4 tunes it with the retrieval evaluation.
DEFAULT_MAX_CHUNK_CHARS = 400


class InvalidDocument(ValueError):
    pass


class DocumentKind(StrEnum):
    POLICY = "policy"
    CONTRACT = "contract"
    SOP = "sop"
    CORRESPONDENCE = "correspondence"


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    section: str  # the heading the chunk sits under
    start: int  # character offsets into the document content, end exclusive
    end: int
    content: str


def _heading(block: str) -> str | None:
    first_line = block.split("\n", 1)[0]
    return first_line.lstrip("#").strip() if _HEADING.match(first_line) else None


def chunk_markdown(content: str, max_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> tuple[Chunk, ...]:
    """Chunks never cross a heading and never split a block. Blocks of a section are packed
    while the span stays within ``max_chars``; a heading always travels with the block after
    it, and a single block longer than the limit stays whole."""
    spans: list[tuple[str, int, int]] = []
    section = ""
    current: tuple[int, int] | None = None
    glued = False  # the open chunk holds only a heading so far
    for match in _BLOCK.finditer(content):
        start, end = match.start(), match.start() + len(match.group().rstrip())
        heading = _heading(content[start:end])
        if heading is not None or current is None:
            if current is not None:
                spans.append((section, *current))
            section = heading if heading is not None else section
            current, glued = (start, end), heading is not None
        elif glued or end - current[0] <= max_chars:
            current, glued = (current[0], end), False
        else:
            spans.append((section, *current))
            current = (start, end)
    if current is not None:
        spans.append((section, *current))
    return tuple(
        Chunk(ordinal=i, section=s, start=a, end=b, content=content[a:b])
        for i, (s, a, b) in enumerate(spans)
    )


def sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Document:
    """``key`` names the document across its versions; each version has its own ``id``."""

    id: uuid.UUID
    key: str
    kind: DocumentKind
    title: str
    version: int
    content: str
    content_sha256: str
    effective_from: date
    chunks: tuple[Chunk, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise InvalidDocument("a document version starts at 1")
        if not self.key.strip():
            raise InvalidDocument("a document needs a key")
        if self.content_sha256 != sha256_of(self.content):
            raise InvalidDocument("the content hash does not match the content")
        if [c.ordinal for c in self.chunks] != list(range(len(self.chunks))) or not self.chunks:
            raise InvalidDocument("chunk ordinals are contiguous from 0")
        for chunk in self.chunks:
            if self.content[chunk.start : chunk.end] != chunk.content or not chunk.content:
                raise InvalidDocument(f"chunk {chunk.ordinal} is not the document text at its span")

    @classmethod
    def first(
        cls,
        *,
        id: uuid.UUID,
        key: str,
        kind: DocumentKind,
        content: str,
        effective_from: date,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    ) -> Document:
        return cls._version(id, key, kind, 1, content, effective_from, max_chunk_chars)

    def revise(
        self,
        *,
        id: uuid.UUID,
        content: str,
        effective_from: date,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    ) -> Document | None:
        """The next version, or None when the content is unchanged (re-ingesting is a no-op)."""
        if sha256_of(content) == self.content_sha256:
            return None
        version = self.version + 1
        return self._version(
            id, self.key, self.kind, version, content, effective_from, max_chunk_chars
        )

    @classmethod
    def _version(
        cls,
        id: uuid.UUID,
        key: str,
        kind: DocumentKind,
        version: int,
        content: str,
        effective_from: date,
        max_chunk_chars: int,
    ) -> Document:
        if not content.strip():
            raise InvalidDocument("a document needs content")
        chunks = chunk_markdown(content, max_chunk_chars)
        title = _heading(chunks[0].content)
        if title is None or not chunks[0].content.startswith("# "):
            raise InvalidDocument("a document starts with a '# ' title")
        return cls(
            id=id,
            key=key,
            kind=kind,
            title=title,
            version=version,
            content=content,
            content_sha256=sha256_of(content),
            effective_from=effective_from,
            chunks=chunks,
        )
