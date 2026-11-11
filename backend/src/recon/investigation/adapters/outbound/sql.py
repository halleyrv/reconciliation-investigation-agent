"""PostgreSQL persistence of the Investigation context.

Discrepancies are read from Reconciliation's tables with read-only SQL (bounded-contexts.md:
foreign keys point upstream only); no Reconciliation code is imported.
"""

import uuid
from types import TracebackType
from typing import Self

from sqlalchemy import Row, column, select, table, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from recon.investigation.adapters.outbound.orm import CaseRow, OutboxRow
from recon.investigation.application.ports import (
    CaseDetail,
    CaseFilter,
    DiscrepancySnapshot,
    DiscrepancyView,
    HistoryEntry,
    RecordRef,
)
from recon.investigation.domain.case import CaseStatus, Priority, ReconciliationCase
from recon.shared_kernel.actor import Actor, ActorType
from recon.shared_kernel.events import DomainEvent, outbox_columns


def _case_from_row(row: CaseRow) -> ReconciliationCase:
    return ReconciliationCase(
        id=row.id,
        discrepancy_id=row.discrepancy_id,
        status=CaseStatus(row.status),
        priority=Priority(row.priority),
        opened_at=row.opened_at,
        version=row.version,
        assignee_id=row.assignee_id,
        closed_at=row.closed_at,
    )


class SqlAlchemyCases:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_discrepancy(self, discrepancy_id: uuid.UUID) -> ReconciliationCase | None:
        row = self._session.scalars(
            select(CaseRow).where(CaseRow.discrepancy_id == discrepancy_id)
        ).one_or_none()
        return None if row is None else _case_from_row(row)

    def get(self, case_id: uuid.UUID) -> ReconciliationCase | None:
        row = self._session.get(CaseRow, case_id)
        return None if row is None else _case_from_row(row)

    def update(self, case: ReconciliationCase, expected_version: int) -> bool:
        # the version predicate is the lock: a concurrent writer's commit makes it match nothing
        updated = self._session.execute(
            update(CaseRow)
            .where(CaseRow.id == case.id, CaseRow.version == expected_version)
            .values(
                priority=case.priority.value, assignee_id=case.assignee_id, version=case.version
            )
            .returning(CaseRow.id)
            .execution_options(synchronize_session=False)
        ).first()
        return updated is not None

    def add(self, case: ReconciliationCase) -> bool:
        # waits for a concurrent insert of the same discrepancy, then skips it
        inserted = self._session.execute(
            insert(CaseRow)
            .values(
                id=case.id,
                discrepancy_id=case.discrepancy_id,
                status=case.status.value,
                priority=case.priority.value,
                assignee_id=case.assignee_id,
                opened_at=case.opened_at,
                closed_at=case.closed_at,
                version=case.version,
            )
            .on_conflict_do_nothing(index_elements=[CaseRow.discrepancy_id])
            .returning(CaseRow.id)
        ).first()
        return inserted is not None


class SqlDiscrepancies:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, discrepancy_id: uuid.UUID) -> DiscrepancyView | None:
        row = self._session.execute(
            text("SELECT id, severity FROM recon.discrepancies WHERE id = :id"),
            {"id": discrepancy_id},
        ).first()
        return None if row is None else DiscrepancyView(row.id, row.severity)


# the exclusive arc of recon.discrepancy_records: one typed column per source record table
_RECORD_COLUMNS = {
    "order": "order_id",
    "payment": "payment_id",
    "refund": "refund_id",
    "fee": "fee_id",
    "settlement": "settlement_id",
    "bank_transaction": "bank_transaction_id",
    "authorization": "authorization_id",
}


# the columns of recon.discrepancies the case filters need, named without its ORM model
_DISCREPANCIES = table(
    "discrepancies", column("id"), column("type"), column("run_id"), schema="recon"
)


def _snapshot(row: Row[tuple[object, ...]]) -> DiscrepancySnapshot:
    m = row._mapping
    return DiscrepancySnapshot(
        id=m["id"],
        run_id=m["run_id"],
        type=m["type"],
        severity=m["severity"],
        expected_minor=m["expected_minor"],
        actual_minor=m["actual_minor"],
        delta_minor=m["delta_minor"],
        currency=m["currency"],
        status=m["status"],
        detected_at=m["detected_at"],
    )


class SqlCaseQueries:
    """Read-only, each call its own short transaction. The discrepancy, its records and the
    audit trail are read with SQL over ``recon`` and ``audit``; no other context is imported."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def detail(self, case_id: uuid.UUID) -> CaseDetail | None:
        with self._session_factory() as session:
            case = session.get(CaseRow, case_id)
            if case is None:
                return None
            discrepancy = session.execute(
                text(
                    "SELECT id, run_id, type, severity, expected_minor, actual_minor,"
                    " delta_minor, currency, status, detected_at"
                    " FROM recon.discrepancies WHERE id = :id"
                ),
                {"id": case.discrepancy_id},
            ).one()
            columns = ", ".join(_RECORD_COLUMNS.values())
            records = [
                RecordRef(kind, record_id)
                for row in session.execute(
                    text(
                        f"SELECT {columns} FROM recon.discrepancy_records"
                        " WHERE discrepancy_id = :id ORDER BY id"
                    ),
                    {"id": case.discrepancy_id},
                )
                for kind, record_id in zip(_RECORD_COLUMNS, row, strict=True)
                if record_id is not None
            ]
            return CaseDetail(_case_from_row(case), _snapshot(discrepancy), records)

    def cases(
        self, where: CaseFilter, after: uuid.UUID | None, limit: int
    ) -> list[ReconciliationCase]:
        query = select(CaseRow).order_by(CaseRow.id).limit(limit)
        if after is not None:
            query = query.where(CaseRow.id > after)
        if where.status is not None:
            query = query.where(CaseRow.status == where.status.value)
        if where.discrepancy_type is not None or where.run_id is not None:
            query = query.join(_DISCREPANCIES, _DISCREPANCIES.c.id == CaseRow.discrepancy_id)
        if where.discrepancy_type is not None:
            query = query.where(_DISCREPANCIES.c.type == where.discrepancy_type)
        if where.run_id is not None:
            query = query.where(_DISCREPANCIES.c.run_id == where.run_id)
        with self._session_factory() as session:
            return [_case_from_row(row) for row in session.scalars(query)]

    def history(self, case_id: uuid.UUID) -> list[HistoryEntry] | None:
        with self._session_factory() as session:
            if session.get(CaseRow, case_id) is None:
                return None
            rows = session.execute(
                text(
                    "SELECT event_type, event_version, occurred_at, actor_type, actor_id, payload"
                    " FROM audit.events"
                    " WHERE aggregate_type = 'ReconciliationCase' AND aggregate_id = :id"
                    " ORDER BY id"
                ),
                {"id": case_id},
            )
            return [
                HistoryEntry(
                    r.event_type,
                    r.event_version,
                    r.occurred_at,
                    Actor(ActorType(r.actor_type), r.actor_id),
                    r.payload,
                )
                for r in rows
            ]


class SqlAlchemyInvestigationUnitOfWork:
    """One database transaction per ``with`` block; leaving it without ``commit`` rolls back."""

    cases: SqlAlchemyCases
    discrepancies: SqlDiscrepancies

    def __init__(self, session_factory: sessionmaker[Session], *, actor: Actor) -> None:
        self._session_factory = session_factory
        self._actor = actor  # stamped on every event this unit of work writes (ADR-0018)

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.cases = SqlAlchemyCases(self._session)
        self.discrepancies = SqlDiscrepancies(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._session.rollback()
        self._session.close()

    def commit(self) -> None:
        self._session.commit()

    def add_event(self, event: DomainEvent) -> None:
        self._session.add(OutboxRow(**outbox_columns(event, self._actor)))
