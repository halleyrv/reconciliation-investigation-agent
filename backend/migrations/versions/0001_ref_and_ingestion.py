"""ref and ingestion schemas (Phase 2a).

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

SHA = "CHAR(64) NOT NULL CHECK ({0} ~ '^[0-9a-f]{{64}}$')"
MONEY = "{0} BIGINT NOT NULL CHECK ({0} > 0), currency CHAR(3) NOT NULL REFERENCES ref.currencies"
# Columns every canonical source record table shares (ADR-0003, register R1).
RECORD = """
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL,
    external_id TEXT NOT NULL CHECK (external_id <> ''),
    raw_record_id UUID NOT NULL UNIQUE,
    FOREIGN KEY (raw_record_id, source_id) REFERENCES ingestion.raw_records (id, source_id),
    UNIQUE (source_id, external_id)"""

UPGRADE = f"""
CREATE SCHEMA ref;
CREATE TABLE ref.currencies (
    code CHAR(3) PRIMARY KEY CHECK (code ~ '^[A-Z]{{3}}$'),
    minor_unit SMALLINT NOT NULL CHECK (minor_unit BETWEEN 0 AND 4)
);
CREATE TABLE ref.source_kinds (code TEXT PRIMARY KEY);
CREATE TABLE ref.fee_types (code TEXT PRIMARY KEY, description TEXT NOT NULL);
INSERT INTO ref.currencies VALUES ('USD', 2);
INSERT INTO ref.source_kinds VALUES ('ecommerce'), ('gateway'), ('bank'), ('authorization');
INSERT INTO ref.fee_types VALUES ('processing', 'Gateway processing fee per captured payment');

CREATE SCHEMA ingestion;
CREATE TABLE ingestion.data_sources (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL REFERENCES ref.source_kinds,
    name TEXT NOT NULL UNIQUE
);
INSERT INTO ingestion.data_sources VALUES
    ('00000000-0000-0000-0000-00000000a001', 'ecommerce', 'shop'),
    ('00000000-0000-0000-0000-00000000a002', 'gateway', 'gateway'),
    ('00000000-0000-0000-0000-00000000a003', 'bank', 'bank'),
    ('00000000-0000-0000-0000-00000000a004', 'authorization', 'back_office');

CREATE TABLE ingestion.import_batches (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES ingestion.data_sources,
    record_type TEXT NOT NULL CHECK (record_type IN ('orders', 'payments', 'refunds', 'fees',
        'settlements', 'bank_transactions', 'authorizations')),
    file_name TEXT NOT NULL CHECK (file_name <> ''),
    file_sha256 {SHA.format("file_sha256")},
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    row_count INT NOT NULL CHECK (row_count >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    CHECK ((status IN ('completed', 'failed')) = (finished_at IS NOT NULL)),
    UNIQUE (source_id, file_sha256),
    UNIQUE (id, source_id)
);
CREATE TABLE ingestion.import_batch_errors (
    batch_id UUID NOT NULL REFERENCES ingestion.import_batches,
    ordinal INT NOT NULL CHECK (ordinal > 0),
    line_no INT NOT NULL CHECK (line_no >= 0),
    field TEXT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (batch_id, ordinal)
);
CREATE TABLE ingestion.raw_records (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL,
    source_id UUID NOT NULL,
    line_no INT NOT NULL CHECK (line_no > 0),
    payload JSONB NOT NULL,
    payload_sha256 {SHA.format("payload_sha256")},
    FOREIGN KEY (batch_id, source_id) REFERENCES ingestion.import_batches (id, source_id),
    UNIQUE (batch_id, line_no),
    UNIQUE (id, source_id),
    UNIQUE (id, payload_sha256)         -- target for source_conflicts (register R12)
);

CREATE TABLE ingestion.orders ({RECORD},
    customer_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    {MONEY.format("amount_minor")},
    status TEXT NOT NULL,
    placed_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE ingestion.payments ({RECORD},
    order_external_ref TEXT NOT NULL,
    gateway TEXT NOT NULL,
    {MONEY.format("amount_minor")},
    captured_at TIMESTAMPTZ NOT NULL,
    settlement_batch_ref TEXT NOT NULL
);
CREATE TABLE ingestion.refunds ({RECORD},
    payment_external_ref TEXT NOT NULL,
    gateway TEXT NOT NULL,
    {MONEY.format("amount_minor")},
    refunded_at TIMESTAMPTZ NOT NULL,
    settlement_batch_ref TEXT NOT NULL
);
CREATE TABLE ingestion.fees ({RECORD},
    payment_external_ref TEXT NOT NULL,
    gateway TEXT NOT NULL,
    fee_type TEXT NOT NULL REFERENCES ref.fee_types,
    {MONEY.format("amount_minor")},
    settlement_batch_ref TEXT NOT NULL
);
CREATE TABLE ingestion.settlements ({RECORD},
    gateway TEXT NOT NULL,
    batch_date DATE NOT NULL,
    {MONEY.format("net_amount_minor")}
);
CREATE TABLE ingestion.bank_transactions ({RECORD},
    account_ref TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('credit', 'debit')),
    value_date DATE NOT NULL,
    {MONEY.format("amount_minor")},
    description TEXT NOT NULL,
    description_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', description)) STORED
);
CREATE TABLE ingestion.authorizations ({RECORD},
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('refund', 'write_off')),
    subject_external_ref TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    {MONEY.format("max_amount_minor")}
);

CREATE TABLE ingestion.source_conflicts (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL,
    record_type TEXT NOT NULL CHECK (record_type IN ('orders', 'payments', 'refunds', 'fees',
        'settlements', 'bank_transactions', 'authorizations')),
    external_id TEXT NOT NULL,
    existing_raw_record_id UUID NOT NULL,
    incoming_raw_record_id UUID NOT NULL UNIQUE,
    incoming_payload_sha256 CHAR(64) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (incoming_raw_record_id, incoming_payload_sha256)
        REFERENCES ingestion.raw_records (id, payload_sha256),
    UNIQUE (source_id, record_type, external_id, incoming_payload_sha256),
    FOREIGN KEY (existing_raw_record_id, source_id)
        REFERENCES ingestion.raw_records (id, source_id),
    FOREIGN KEY (incoming_raw_record_id, source_id)
        REFERENCES ingestion.raw_records (id, source_id),
    CHECK (existing_raw_record_id <> incoming_raw_record_id)
);
CREATE TABLE ingestion.outbox (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_version INT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ
);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP SCHEMA ingestion CASCADE; DROP SCHEMA ref CASCADE;")
