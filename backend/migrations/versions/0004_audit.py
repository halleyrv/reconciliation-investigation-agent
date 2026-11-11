"""audit schema and the actor of every outbox event (Phase 2c, ADR-0018).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"

OUTBOXES = ("ingestion.outbox", "recon.outbox", "investigation.outbox")
ACTOR_TYPES = "('user', 'agent', 'system')"


def _actor_columns(outbox: str) -> str:
    # Rows written before 0004 have no known actor; the defaults name that and are dropped.
    return f"""
ALTER TABLE {outbox}
    ADD COLUMN actor_type TEXT NOT NULL DEFAULT 'system' CHECK (actor_type IN {ACTOR_TYPES}),
    ADD COLUMN actor_id TEXT NOT NULL DEFAULT 'before-0004' CHECK (actor_id <> ''),
    ADD COLUMN aggregate_type TEXT CHECK (aggregate_type <> ''),
    ADD COLUMN aggregate_id UUID;
ALTER TABLE {outbox} ALTER COLUMN actor_type DROP DEFAULT, ALTER COLUMN actor_id DROP DEFAULT;
-- Events delivered before the audit trail existed are delivered again so it records them;
-- every handler is idempotent.
UPDATE {outbox} SET published_at = NULL;
"""


UPGRADE = f"""
{"".join(_actor_columns(o) for o in OUTBOXES)}
CREATE SCHEMA audit;

CREATE TABLE audit.events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL CHECK (source <> ''),
    source_event_id BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN {ACTOR_TYPES}),
    actor_id TEXT NOT NULL CHECK (actor_id <> ''),
    aggregate_type TEXT,
    aggregate_id UUID,
    event_type TEXT NOT NULL,
    event_version INT NOT NULL,
    payload JSONB NOT NULL,
    prev_sha256 CHAR(64) UNIQUE CHECK (prev_sha256 ~ '^[0-9a-f]{{64}}$'),
    sha256 CHAR(64) NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
    -- an outbox event is audited once, however often it is delivered
    UNIQUE (source, source_event_id)
);
CREATE INDEX events_aggregate_idx ON audit.events (aggregate_type, aggregate_id);

-- Append-only for every role, the application's included (AC-2c.6).
CREATE FUNCTION audit.reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.events is append-only: % rejected', TG_OP;
END;
$$;
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.reject_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    columns = (
        "DROP COLUMN actor_type, DROP COLUMN actor_id, DROP COLUMN aggregate_type,"
        " DROP COLUMN aggregate_id"
    )
    op.execute(
        "DROP SCHEMA audit CASCADE;" + "".join(f"ALTER TABLE {o} {columns};" for o in OUTBOXES)
    )
