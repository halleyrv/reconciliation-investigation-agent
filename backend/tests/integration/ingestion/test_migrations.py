import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from recon.bootstrap.migrations import downgrade, upgrade
from tests.integration.conftest import create_database, drop_database

CONTEXT_SCHEMAS = {"ref", "ingestion", "recon", "investigation", "audit"}


def test_migrations_go_up_from_empty_and_back_to_base_with_every_table_in_its_schema() -> None:
    url = create_database()
    engine = create_engine(url)
    tables = text(
        "SELECT table_schema, table_name FROM information_schema.tables"
        " WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
    )
    try:
        upgrade(url)
        with engine.connect() as connection:
            after_upgrade = {tuple(row) for row in connection.execute(tables)}
        downgrade(url)
        with engine.connect() as connection:
            after_downgrade = {tuple(row) for row in connection.execute(tables)}
    finally:
        engine.dispose()
        drop_database(url)

    outside = {t for t in after_upgrade if t[0] not in CONTEXT_SCHEMAS}
    assert outside == {("public", "alembic_version")}
    assert {
        ("ingestion", "orders"),
        ("ingestion", "source_conflicts"),
        ("ref", "currencies"),
        ("ref", "discrepancy_types"),
        ("recon", "reconciliation_runs"),
        ("recon", "discrepancies"),
        ("investigation", "cases"),
        ("investigation", "outbox"),
        ("audit", "events"),
    } <= after_upgrade
    assert after_downgrade == {("public", "alembic_version")}


def test_a_replaced_run_keeps_the_database_from_going_below_0005() -> None:
    url = create_database()
    engine = create_engine(url)
    try:
        upgrade(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO recon.reconciliation_runs (id, period, ruleset_version, status,"
                    " started_at, finished_at) VALUES (gen_random_uuid(),"
                    " '[2026-10-01,2026-11-01)', 'v1', 'superseded', now(), now())"
                )
            )
        with pytest.raises(DBAPIError, match="a replaced run exists"):
            downgrade(url, "0004")
        with engine.connect() as connection:  # refused before any change
            revision = connection.execute(text("SELECT version_num FROM alembic_version"))
            assert revision.scalar_one() == "0005"
    finally:
        engine.dispose()
        drop_database(url)
