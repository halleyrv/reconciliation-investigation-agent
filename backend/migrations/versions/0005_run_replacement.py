"""Run replacement: superseded runs and discrepancies, case close reason (Phase 2c, ADR-0021).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"

UPGRADE = """
ALTER TABLE recon.reconciliation_runs
    DROP CONSTRAINT reconciliation_runs_status_check,
    DROP CONSTRAINT reconciliation_runs_check,
    DROP CONSTRAINT reconciliation_runs_live_period_excl,
    ADD CONSTRAINT reconciliation_runs_status_check
        CHECK (status IN ('running', 'completed', 'failed', 'superseded')),
    ADD CONSTRAINT reconciliation_runs_check
        CHECK ((status <> 'running') = (finished_at IS NOT NULL)),
    -- A replacing run runs next to the completed run it replaces, so running and completed
    -- runs are kept apart separately: two of either never share a day (ADR-0016, ADR-0021).
    ADD CONSTRAINT reconciliation_runs_running_period_excl EXCLUDE USING gist
        (ruleset_version WITH =, period WITH &&) WHERE (status = 'running'),
    ADD CONSTRAINT reconciliation_runs_completed_period_excl EXCLUDE USING gist
        (ruleset_version WITH =, period WITH &&) WHERE (status = 'completed');

-- The discrepancy of the replacing run with the same fingerprint, if it found it again.
ALTER TABLE recon.discrepancies
    ADD COLUMN superseded_by UUID UNIQUE REFERENCES recon.discrepancies,
    ADD CONSTRAINT discrepancies_superseded_by_check
        CHECK (superseded_by IS NULL OR status = 'superseded');

ALTER TABLE investigation.cases
    ADD COLUMN close_reason TEXT CHECK (close_reason IN ('superseded')),
    ADD CONSTRAINT cases_close_reason_resolved_check
        CHECK (close_reason IS NULL OR status = 'resolved');
"""

# A replaced run has no meaning under 0004: refuse instead of dropping or rewriting history.
DOWNGRADE = """
DO $$
BEGIN
    IF EXISTS (SELECT FROM recon.reconciliation_runs WHERE status = 'superseded') THEN
        RAISE EXCEPTION 'a replaced run exists; revision 0004 cannot hold it'
            USING HINT = 'downgrade an empty database, or drop and recreate this one';
    END IF;
END $$;

ALTER TABLE investigation.cases DROP COLUMN close_reason;

ALTER TABLE recon.discrepancies DROP COLUMN superseded_by;

ALTER TABLE recon.reconciliation_runs
    DROP CONSTRAINT reconciliation_runs_completed_period_excl,
    DROP CONSTRAINT reconciliation_runs_running_period_excl,
    DROP CONSTRAINT reconciliation_runs_check,
    DROP CONSTRAINT reconciliation_runs_status_check,
    ADD CONSTRAINT reconciliation_runs_status_check
        CHECK (status IN ('running', 'completed', 'failed')),
    ADD CONSTRAINT reconciliation_runs_check
        CHECK ((status IN ('completed', 'failed')) = (finished_at IS NOT NULL)),
    ADD CONSTRAINT reconciliation_runs_live_period_excl EXCLUDE USING gist
        (ruleset_version WITH =, period WITH &&) WHERE (status <> 'failed');
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
