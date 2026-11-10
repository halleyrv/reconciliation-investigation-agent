"""Integration tests run against the Compose PostgreSQL (``scripts/check.sh`` starts it).
Each session creates its own database, migrates it, and drops it afterwards."""

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, make_url, text

from recon.bootstrap.migrations import upgrade
from recon.bootstrap.settings import database_url

SAMPLE = Path(__file__).parents[3] / "simulator" / "samples" / "orders-200-seed-42"


def create_database() -> str:
    url = make_url(database_url())
    name = f"recon_test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return url.set(database=name).render_as_string(hide_password=False)


def drop_database(url: str) -> None:
    name = make_url(url).database
    admin = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated_url() -> Iterator[str]:
    url = create_database()
    upgrade(url)
    yield url
    drop_database(url)


@pytest.fixture
def engine(migrated_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_url)
    yield engine
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE recon.outbox, recon.discrepancy_records, recon.discrepancies,"
                " recon.match_group_members, recon.match_groups, recon.reconciliation_runs,"
                " recon.fee_schedules, recon.holidays, ingestion.outbox,"
                " ingestion.source_conflicts, ingestion.orders,"
                " ingestion.payments, ingestion.refunds, ingestion.fees, ingestion.settlements,"
                " ingestion.bank_transactions, ingestion.authorizations, ingestion.raw_records,"
                " ingestion.import_batch_errors, ingestion.import_batches"
            )
        )
    engine.dispose()


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    return Path(shutil.copytree(SAMPLE, tmp_path / "export"))
