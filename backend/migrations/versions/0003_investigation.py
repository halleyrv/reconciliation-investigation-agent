"""investigation schema: reconciliation cases and their outbox (Phase 2c).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

UPGRADE = """
CREATE SCHEMA investigation;

CREATE TABLE investigation.cases (
    id UUID PRIMARY KEY,
    discrepancy_id UUID NOT NULL UNIQUE REFERENCES recon.discrepancies,
    status TEXT NOT NULL
        CHECK (status IN ('open', 'investigating', 'awaiting_approval', 'resolved', 'escalated')),
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    assignee_id TEXT CHECK (assignee_id <> ''),
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    version INT NOT NULL CHECK (version >= 1),
    CHECK ((status IN ('resolved', 'escalated')) = (closed_at IS NOT NULL))
);

CREATE TABLE investigation.outbox (
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
    op.execute("DROP SCHEMA investigation CASCADE;")
