"""PostgreSQL persistence of the Investigation context.

Discrepancies are read from Reconciliation's tables with read-only SQL (bounded-contexts.md:
foreign keys point upstream only); no Reconciliation code is imported.
"""

import uuid
from types import TracebackType
from typing import Self

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from recon.investigation.adapters.outbound.orm import CaseRow, OutboxRow
from recon.investigation.application.ports import DiscrepancyView
from recon.investigation.domain.case import CaseStatus, Priority, ReconciliationCase
from recon.shared_kernel.actor import Actor
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
