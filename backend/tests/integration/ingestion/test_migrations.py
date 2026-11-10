from sqlalchemy import create_engine, text

from recon.bootstrap.migrations import downgrade, upgrade
from tests.integration.conftest import create_database, drop_database

CONTEXT_SCHEMAS = {"ref", "ingestion", "recon"}


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
    } <= after_upgrade
    assert after_downgrade == {("public", "alembic_version")}
