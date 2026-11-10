"""recon schema: reference data, runs, match groups and discrepancies (Phase 2b).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

# One nullable FK per source record type, exactly one set: an exclusive arc (data-model.md).
RECORD_COLUMNS = {
    "order_id": "ingestion.orders",
    "payment_id": "ingestion.payments",
    "refund_id": "ingestion.refunds",
    "fee_id": "ingestion.fees",
    "settlement_id": "ingestion.settlements",
    "bank_transaction_id": "ingestion.bank_transactions",
    "authorization_id": "ingestion.authorizations",
}
MEMBER_COLUMNS = {k: v for k, v in RECORD_COLUMNS.items() if k != "authorization_id"}


def _one_of(columns: dict[str, str]) -> str:
    fks = ",\n    ".join(f"{c} UUID REFERENCES {t}" for c, t in columns.items())
    return f"{fks},\n    CHECK (num_nonnulls({', '.join(columns)}) = 1)"


SEVERITIES = "('low', 'medium', 'high')"

UPGRADE = f"""
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE ref.discrepancy_types (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    default_severity TEXT NOT NULL CHECK (default_severity IN {SEVERITIES})
);
INSERT INTO ref.discrepancy_types VALUES
    ('duplicate_payment', 'Two payments claim the same order with the same amount', 'high'),
    ('unauthorized_refund', 'Refund with no authorization covering its amount before it', 'high'),
    ('fee_mismatch', 'Fee differs from the fee schedule applied to the payment', 'medium'),
    ('missing_in_bank', 'Settlement batch never paid out by the bank', 'high'),
    ('missing_in_gateway', 'Bank credit or order with no gateway counterpart', 'high'),
    ('missing_in_orders', 'Gateway payment for an order the shop never sent', 'medium'),
    ('underpayment', 'Payment below the order total', 'medium'),
    ('settlement_delayed', 'Bank credit later than batch date plus the settlement lag', 'low'),
    ('amount_mismatch', 'Bank credit or declared net differs from what it should equal', 'high'),
    ('reference_mismatch', 'Reference that resolves to no record or only once normalized', 'low'),
    ('sequence_violation', 'Timestamps out of the order, payment, settlement sequence', 'low'),
    ('duplicate_refund', 'Two refunds of the same payment for the same amount', 'high'),
    ('source_conflict', 'A source re-sent a known record with a different payload', 'low');

CREATE SCHEMA recon;

CREATE TABLE recon.fee_schedules (
    id UUID PRIMARY KEY,
    gateway TEXT NOT NULL CHECK (gateway <> ''),
    fee_type TEXT NOT NULL REFERENCES ref.fee_types,
    rate_bps INT NOT NULL CHECK (rate_bps >= 0),
    fixed_minor BIGINT NOT NULL CHECK (fixed_minor >= 0),
    currency CHAR(3) NOT NULL REFERENCES ref.currencies,
    valid_during DATERANGE NOT NULL
        CHECK (NOT isempty(valid_during) AND lower_inc(valid_during)
            AND NOT lower_inf(valid_during)),
    policy_document_id UUID,
    EXCLUDE USING gist (gateway WITH =, fee_type WITH =, valid_during WITH &&)
);
CREATE TABLE recon.holidays (day DATE PRIMARY KEY);

CREATE TABLE recon.reconciliation_runs (
    id UUID PRIMARY KEY,
    period DATERANGE NOT NULL CHECK (NOT isempty(period)),
    ruleset_version TEXT NOT NULL CHECK (ruleset_version <> ''),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    CHECK ((status IN ('completed', 'failed')) = (finished_at IS NOT NULL))
);
-- One live run per period and ruleset; a failed run stays for the record and may be retried.
CREATE UNIQUE INDEX reconciliation_runs_live_key
    ON recon.reconciliation_runs (period, ruleset_version) WHERE status <> 'failed';

CREATE TABLE recon.match_groups (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES recon.reconciliation_runs,
    rule_code TEXT NOT NULL CHECK (rule_code <> ''),
    UNIQUE (id, run_id)
);
CREATE TABLE recon.match_group_members (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    group_id UUID NOT NULL,
    run_id UUID NOT NULL,
    role TEXT NOT NULL CHECK (role <> ''),
    {_one_of(MEMBER_COLUMNS)},
    FOREIGN KEY (group_id, run_id) REFERENCES recon.match_groups (id, run_id),
    {", ".join(f"UNIQUE (run_id, {c})" for c in MEMBER_COLUMNS)}
);

CREATE TABLE recon.discrepancies (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES recon.reconciliation_runs,
    type TEXT NOT NULL REFERENCES ref.discrepancy_types,
    severity TEXT NOT NULL CHECK (severity IN {SEVERITIES}),
    expected_minor BIGINT NOT NULL,
    actual_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES ref.currencies,
    delta_minor BIGINT GENERATED ALWAYS AS (actual_minor - expected_minor) STORED,
    fingerprint CHAR(64) NOT NULL UNIQUE CHECK (fingerprint ~ '^[0-9a-f]{{64}}$'),
    status TEXT NOT NULL CHECK (status IN ('detected', 'superseded')),
    detected_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE recon.discrepancy_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discrepancy_id UUID NOT NULL REFERENCES recon.discrepancies,
    {_one_of(RECORD_COLUMNS)},
    {", ".join(f"UNIQUE (discrepancy_id, {c})" for c in RECORD_COLUMNS)}
);

CREATE TABLE recon.outbox (
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
    # btree_gist stays: it may have existed before 0002, and other objects may depend on it.
    op.execute("DROP SCHEMA recon CASCADE; DROP TABLE ref.discrepancy_types;")
