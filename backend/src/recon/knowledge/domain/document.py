"""Document: one version of a policy text with its chunks. A chunk is an exact span of the
text, so a quote attributed to a chunk can be checked against the document it came from."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# A block is a heading line, or a run of non-blank lines that are not headings: a paragraph,
# a list or a table. A heading interrupts a paragraph even without a blank line before it.
_HEADING_LINE = r"#{1,6}(?: .*)?$"
_BLOCK = re.compile(rf"^{_HEADING_LINE}|(?:^(?!{_HEADING_LINE})[ \t]*\S.*(?:\n|$))+", re.MULTILINE)
_HEADING = re.compile(_HEADING_LINE)
# Chosen by the retrieval evaluation (ADR-0023): 200 ties it, 800 becomes document retrieval.
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


type Span = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Section:
    title: str
    has_heading: bool  # False only for text before the first heading
    blocks: list[Span]


def _sections(content: str) -> list[_Section]:
    """The blocks of the text grouped under the heading they follow."""
    sections: list[_Section] = []
    for match in _BLOCK.finditer(content):
        span = (match.start(), match.start() + len(match.group().rstrip()))
        heading = _heading(content[span[0] : span[1]])
        if heading is None and sections:
            sections[-1].blocks.append(span)
            continue
        sections.append(_Section(heading or "", heading is not None, [span]))
    return sections


def _pack(blocks: list[Span], max_chars: int, starts_with_heading: bool) -> list[Span]:
    """Packs consecutive blocks while the span stays within ``max_chars``."""
    if starts_with_heading and len(blocks) > 1:
        blocks = [(blocks[0][0], blocks[1][1]), *blocks[2:]]  # a heading never stands alone
    packed = [blocks[0]]
    for start, end in blocks[1:]:
        if end - packed[-1][0] > max_chars:
            packed.append((start, end))
            continue
        packed[-1] = (packed[-1][0], end)
    return packed


def chunk_markdown(content: str, max_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> tuple[Chunk, ...]:
    """Chunks never cross a heading and never split a block. Blocks of a section are packed
    while the span stays within ``max_chars``; a heading always travels with the block after
    it, and a single block longer than the limit stays whole."""
    spans = [
        (section.title, span)
        for section in _sections(content)
        for span in _pack(section.blocks, max_chars, section.has_heading)
    ]
    return tuple(
        Chunk(ordinal=i, section=section, start=a, end=b, content=content[a:b])
        for i, (section, (a, b)) in enumerate(spans)
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
        if not self.chunks:
            raise InvalidDocument("a document has at least one chunk")
        if [c.ordinal for c in self.chunks] != list(range(len(self.chunks))):
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
        if not title or not chunks[0].content.startswith("# "):
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
