"""knowledge schema: versioned documents and their chunks, searchable by full text and by
embedding (Phase 3, ADR-0006, ADR-0023).

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"

UPGRADE = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA knowledge;

-- One row per version. A version is never changed: a new text is a new version, and a text
-- that returns to an earlier one is a new version too, so the hash is not unique on its own.
CREATE TABLE knowledge.documents (
    id UUID PRIMARY KEY,
    key TEXT NOT NULL CHECK (key <> ''),
    kind TEXT NOT NULL CHECK (kind IN ('policy', 'contract', 'sop', 'correspondence')),
    title TEXT NOT NULL CHECK (title <> ''),
    version INT NOT NULL CHECK (version >= 1),
    content TEXT NOT NULL CHECK (content <> ''),
    content_sha256 CHAR(64) NOT NULL,
    embedding_model TEXT NOT NULL CHECK (embedding_model <> ''),
    effective_from DATE NOT NULL,
    UNIQUE (key, version)
);

CREATE TABLE knowledge.document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge.documents,
    ordinal INT NOT NULL CHECK (ordinal >= 0),
    section TEXT NOT NULL,
    start_offset INT NOT NULL CHECK (start_offset >= 0),
    end_offset INT NOT NULL CHECK (end_offset > start_offset),
    content TEXT NOT NULL CHECK (content <> ''),
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding VECTOR(384) NOT NULL, -- BAAI/bge-small-en-v1.5 (ADR-0023)
    UNIQUE (document_id, ordinal)
);

CREATE INDEX document_chunks_content_tsv_idx ON knowledge.document_chunks USING gin (content_tsv);
CREATE INDEX document_chunks_embedding_idx
    ON knowledge.document_chunks USING hnsw (embedding vector_cosine_ops);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP SCHEMA knowledge CASCADE; DROP EXTENSION IF EXISTS vector;")
