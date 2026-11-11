import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from recon.ingestion.adapters.outbound.simulator_files import read_export
from recon.ingestion.adapters.outbound.sql import SqlAlchemyIngestionUnitOfWork
from recon.ingestion.application.import_export import ImportExport
from recon.investigation.adapters.outbound.sql import SqlAlchemyInvestigationUnitOfWork
from recon.investigation.application.open_case import DiscrepancyNotFound, OpenCase
from recon.reconciliation.adapters.inbound.reference_file import read_reference_file
from recon.reconciliation.adapters.outbound.sql import SqlAlchemyReconciliationUnitOfWork
from recon.reconciliation.application.load_reference_data import LoadReferenceData
from recon.reconciliation.application.reconcile_period import ReconcilePeriod
from recon.reconciliation.domain.results import Period
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.ports import SystemClock, UuidIdGenerator

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"


def _rows(engine: Engine, sql: str, **params: object) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql), params)]


@pytest.fixture
def reconciled(engine: Engine, sample: Path) -> Engine:
    ImportExport(
        SqlAlchemyIngestionUnitOfWork(sessionmaker(engine), actor=Actor.system("test")),
        SystemClock(),
        UuidIdGenerator(),
    )(read_export(sample))
    recon_uow = SqlAlchemyReconciliationUnitOfWork(sessionmaker(engine), actor=Actor.system("test"))
    LoadReferenceData(recon_uow, UuidIdGenerator())(*read_reference_file(REFERENCE_FILE))
    ReconcilePeriod(recon_uow, SystemClock(), UuidIdGenerator())(
        Period(date(2026, 10, 1), date(2026, 10, 31))
    )
    return engine


def _open_case(engine: Engine) -> OpenCase:
    uow = SqlAlchemyInvestigationUnitOfWork(sessionmaker(engine), actor=Actor.system("test"))
    return OpenCase(uow, SystemClock(), UuidIdGenerator())


def _a_discrepancy(engine: Engine) -> tuple[uuid.UUID, str]:
    [(discrepancy_id, severity)] = _rows(
        engine, "SELECT id, severity FROM recon.discrepancies ORDER BY fingerprint LIMIT 1"
    )
    assert isinstance(discrepancy_id, uuid.UUID) and isinstance(severity, str)
    return discrepancy_id, severity


def test_opening_a_case_persists_it_with_its_event_once(reconciled: Engine) -> None:
    discrepancy_id, severity = _a_discrepancy(reconciled)

    first = _open_case(reconciled)(discrepancy_id)
    again = _open_case(reconciled)(discrepancy_id)

    assert first.created and not again.created and again.case == first.case
    assert _rows(
        reconciled,
        "SELECT id, status, priority, version, assignee_id, closed_at FROM investigation.cases",
    ) == [(first.case.id, "open", severity, 1, None, None)]
    [(event_type, payload)] = _rows(
        reconciled, "SELECT event_type, payload FROM investigation.outbox"
    )
    assert event_type == "CaseOpened"
    assert payload == {
        "occurred_at": first.case.opened_at.isoformat(),
        "case_id": str(first.case.id),
        "discrepancy_id": str(discrepancy_id),
        "priority": severity,
    }


def test_a_case_for_an_unknown_discrepancy_is_refused(reconciled: Engine) -> None:
    with pytest.raises(DiscrepancyNotFound):
        _open_case(reconciled)(uuid.uuid4())

    assert _rows(reconciled, "SELECT count(*) FROM investigation.cases") == [(0,)]


def test_concurrent_openings_of_one_discrepancy_create_one_case(reconciled: Engine) -> None:
    discrepancy_id, _ = _a_discrepancy(reconciled)
    barrier = threading.Barrier(4)

    def open_it() -> uuid.UUID:
        barrier.wait(timeout=10)
        return _open_case(reconciled)(discrepancy_id).case.id

    with ThreadPoolExecutor(4) as pool:
        ids = set(pool.map(lambda _: open_it(), range(4)))

    assert not barrier.broken
    assert len(ids) == 1
    assert _rows(reconciled, "SELECT count(*) FROM investigation.cases") == [(1,)]
    assert _rows(reconciled, "SELECT count(*) FROM investigation.outbox") == [(1,)]


def test_the_database_rejects_a_second_case_and_a_case_without_its_discrepancy(
    reconciled: Engine,
) -> None:
    discrepancy_id, _ = _a_discrepancy(reconciled)
    insert = (
        "INSERT INTO investigation.cases (id, discrepancy_id, status, priority, opened_at, version)"
        " VALUES (:id, :d, 'open', 'low', now(), 1)"
    )
    with reconciled.begin() as connection:
        connection.execute(text(insert), {"id": uuid.uuid4(), "d": discrepancy_id})
    for target in (discrepancy_id, uuid.uuid4()):
        with pytest.raises(IntegrityError), reconciled.begin() as connection:
            connection.execute(text(insert), {"id": uuid.uuid4(), "d": target})


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("status", "'closed'"),
        ("priority", "'urgent'"),
        ("version", "0"),
        ("assignee_id", "''"),
        ("closed_at", "now()"),  # open with a close time
    ],
)
def test_the_database_rejects_a_case_breaking_its_checks(
    reconciled: Engine, column: str, value: str
) -> None:
    discrepancy_id, _ = _a_discrepancy(reconciled)
    values = {"status": "'open'", "priority": "'low'", "version": "1"} | {column: value}
    columns = ", ".join(values)
    with pytest.raises(IntegrityError), reconciled.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO investigation.cases (id, discrepancy_id, opened_at, {columns})"
                f" VALUES (:id, :d, now(), {', '.join(values.values())})"
            ),
            {"id": uuid.uuid4(), "d": discrepancy_id},
        )
    resolved_open = (
        "INSERT INTO investigation.cases (id, discrepancy_id, status, priority, opened_at, version)"
        " VALUES (:id, :d, 'resolved', 'low', now(), 1)"
    )
    with pytest.raises(IntegrityError), reconciled.begin() as connection:
        connection.execute(text(resolved_open), {"id": uuid.uuid4(), "d": discrepancy_id})
