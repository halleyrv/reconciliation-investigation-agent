"""The knowledge schema in PostgreSQL: the document store and the two first-stage searches
(full text and pgvector) over the current version of each document."""

from collections.abc import Sequence

from sqlalchemy import Engine, TextClause, text

from recon.knowledge.adapters.outbound.full_text_ranking import OR_TERMS
from recon.knowledge.application.ports import NO_FILTERS, ChunkHit, RetrievalFilters, Vector
from recon.knowledge.domain.document import Chunk, Document, DocumentKind

_LATEST = text(
    "SELECT id, key, kind, title, version, content, content_sha256, effective_from"
    " FROM knowledge.documents WHERE key = :key ORDER BY version DESC LIMIT 1"
)
_CHUNKS = text(
    "SELECT ordinal, section, start_offset, end_offset, content FROM knowledge.document_chunks"
    " WHERE document_id = :id ORDER BY ordinal"
)
_INSERT_DOCUMENT = text(
    "INSERT INTO knowledge.documents (id, key, kind, title, version, content, content_sha256,"
    " embedding_model, effective_from) VALUES (:id, :key, :kind, :title, :version, :content,"
    " :content_sha256, :embedding_model, :effective_from)"
)
_INSERT_CHUNK = text(
    "INSERT INTO knowledge.document_chunks (document_id, ordinal, section, start_offset,"
    " end_offset, content, embedding) VALUES (:document_id, :ordinal, :section, :start, :end,"
    " :content, CAST(:embedding AS vector))"
)
# The current version of a document is the highest one stored under its key.
_CURRENT = (
    "NOT EXISTS (SELECT FROM knowledge.documents newer"
    " WHERE newer.key = d.key AND newer.version > d.version)"
)
# A NULL array does not narrow the search (RetrievalFilters: None).
_FILTERS = (
    "(CAST(:kinds AS text[]) IS NULL OR d.kind = ANY(CAST(:kinds AS text[])))"
    " AND (CAST(:keys AS text[]) IS NULL OR d.key = ANY(CAST(:keys AS text[])))"
)
_HIT = "c.id AS chunk_id, d.id AS document_id, d.key, d.version, c.ordinal, c.section, c.content"
_FULL_TEXT = text(
    f"""
    WITH {OR_TERMS}
    SELECT {_HIT}, ts_rank_cd(c.content_tsv, q.terms) AS score
    FROM knowledge.document_chunks c JOIN knowledge.documents d ON d.id = c.document_id, q
    WHERE c.content_tsv @@ q.terms AND {_CURRENT} AND {_FILTERS}
    ORDER BY score DESC, d.key, c.ordinal
    LIMIT :limit
    """
)
# The nearest chunks come from the HNSW index alone, then the model and current-version filters
# apply: joined first, the planner starts from documents and sorts every chunk instead. The
# index returns at most hnsw.ef_search (default 40) rows per scan, so that is the candidate pool.
# shortcut: when old versions, other models or filtered-out documents fill the pool, fewer
# than `limit` rows return; raise ef_search or use iterative scans (pgvector >= 0.8) when the
# corpus grows.
VECTOR_CANDIDATES = 40
VECTOR_SEARCH = text(
    f"""
    WITH nearest AS MATERIALIZED (
        SELECT c.id, c.embedding <=> CAST(:query AS vector) AS distance
        FROM knowledge.document_chunks c
        ORDER BY c.embedding <=> CAST(:query AS vector)
        LIMIT {VECTOR_CANDIDATES}
    )
    SELECT {_HIT}, 1 - n.distance AS score
    FROM nearest n JOIN knowledge.document_chunks c ON c.id = n.id
    JOIN knowledge.documents d ON d.id = c.document_id
    WHERE d.embedding_model = :model AND {_CURRENT} AND {_FILTERS}
    ORDER BY n.distance, d.key, c.ordinal
    LIMIT :limit
    """
)


def _literal(vector: Vector) -> str:
    return "[" + ",".join(repr(x) for x in vector) + "]"


class SqlDocumentRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def latest(self, key: str) -> Document | None:
        with self._engine.connect() as connection:
            row = connection.execute(_LATEST, {"key": key}).one_or_none()
            if row is None:
                return None
            chunks = connection.execute(_CHUNKS, {"id": row.id})
            return Document(
                id=row.id,
                key=row.key,
                kind=DocumentKind(row.kind),
                title=row.title,
                version=row.version,
                content=row.content,
                content_sha256=row.content_sha256,
                effective_from=row.effective_from,
                chunks=tuple(
                    Chunk(c.ordinal, c.section, c.start_offset, c.end_offset, c.content)
                    for c in chunks
                ),
            )

    def add(self, document: Document, embedding_model: str, embeddings: Sequence[Vector]) -> None:
        if len(embeddings) != len(document.chunks):
            raise ValueError("one embedding per chunk")
        with self._engine.begin() as connection:
            connection.execute(
                _INSERT_DOCUMENT,
                {
                    "id": document.id,
                    "key": document.key,
                    "kind": document.kind.value,
                    "title": document.title,
                    "version": document.version,
                    "content": document.content,
                    "content_sha256": document.content_sha256,
                    "embedding_model": embedding_model,
                    "effective_from": document.effective_from,
                },
            )
            connection.execute(
                _INSERT_CHUNK,
                [
                    {
                        "document_id": document.id,
                        "ordinal": c.ordinal,
                        "section": c.section,
                        "start": c.start,
                        "end": c.end,
                        "content": c.content,
                        "embedding": _literal(v),
                    }
                    for c, v in zip(document.chunks, embeddings, strict=True)
                ],
            )


class SqlChunkSearch:
    """First-stage searches; each returns at most ``limit`` hits, best first."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def full_text(
        self, query: str, limit: int, filters: RetrievalFilters = NO_FILTERS
    ) -> list[ChunkHit]:
        """Chunks that share at least one stemmed term with the query."""
        return self._hits(_FULL_TEXT, {"query": query, "limit": limit}, filters)

    def vector(
        self, query: Vector, model: str, limit: int, filters: RetrievalFilters = NO_FILTERS
    ) -> list[ChunkHit]:
        """Nearest chunks by cosine similarity, among documents embedded with ``model``: a
        vector of another model is not comparable."""
        params = {"query": _literal(query), "model": model, "limit": limit}
        return self._hits(VECTOR_SEARCH, params, filters)

    def _hits(
        self, statement: TextClause, params: dict[str, object], filters: RetrievalFilters
    ) -> list[ChunkHit]:
        kinds = None if filters.kinds is None else sorted(k.value for k in filters.kinds)
        keys = None if filters.document_keys is None else sorted(filters.document_keys)
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {**params, "kinds": kinds, "keys": keys})
            return [
                ChunkHit(
                    r.chunk_id,
                    r.document_id,
                    r.key,
                    r.version,
                    r.ordinal,
                    r.section,
                    r.content,
                    float(r.score),
                )
                for r in rows
            ]
