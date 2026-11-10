"""PostgreSQL persistence of the Reconciliation context.

Source records are read from Ingestion's canonical tables with read-only SQL
(bounded-contexts.md: Reconciliation reads them, foreign keys point upstream only); no
Ingestion code is imported.
"""

import uuid
from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Any, Self

from sqlalchemy import insert, select, text, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session, sessionmaker

from recon.reconciliation.adapters.outbound.orm import (
    DiscrepancyRecordRow,
    DiscrepancyRow,
    FeeScheduleRow,
    HolidayRow,
    MatchGroupMemberRow,
    MatchGroupRow,
    OutboxRow,
    RunRow,
)
from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.records import (
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    RecordRef,
    Refund,
    Settlement,
    Source,
    SourceConflict,
)
from recon.reconciliation.domain.results import Discrepancy, MatchGroup, Period
from recon.reconciliation.domain.run import ReconciliationRun, RunStatus
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.events import DomainEvent, event_payload
from recon.shared_kernel.money import Money

RECORD_COLUMN: dict[Source, str] = {
    Source.ORDERS: "order_id",
    Source.PAYMENTS: "payment_id",
    Source.REFUNDS: "refund_id",
    Source.FEES: "fee_id",
    Source.SETTLEMENTS: "settlement_id",
    Source.BANK_TRANSACTIONS: "bank_transaction_id",
    Source.AUTHORIZATIONS: "authorization_id",
}

_QUERIES: dict[Source, str] = {
    Source.ORDERS: "SELECT id, external_id, placed_at, amount_minor, currency"
    " FROM ingestion.orders",
    Source.PAYMENTS: "SELECT id, external_id, order_external_ref, gateway, amount_minor, currency,"
    " captured_at, settlement_batch_ref FROM ingestion.payments",
    Source.REFUNDS: "SELECT id, external_id, payment_external_ref, gateway, amount_minor, currency,"
    " refunded_at, settlement_batch_ref FROM ingestion.refunds",
    Source.FEES: "SELECT id, external_id, payment_external_ref, gateway, fee_type, amount_minor,"
    " currency, settlement_batch_ref FROM ingestion.fees",
    Source.SETTLEMENTS: "SELECT id, external_id, gateway, batch_date, net_amount_minor, currency"
    " FROM ingestion.settlements",
    Source.BANK_TRANSACTIONS: "SELECT id, external_id, direction, value_date, amount_minor,"
    " currency, description FROM ingestion.bank_transactions",
    Source.AUTHORIZATIONS: "SELECT id, external_id, subject_kind, subject_external_ref,"
    " approved_at, max_amount_minor, currency FROM ingestion.authorizations",
}


def to_range(period: Period) -> Range[date]:
    return Range(period.start, period.end + timedelta(days=1), bounds="[)")


def to_period(value: Range[date]) -> Period:
    assert value.lower is not None and value.upper is not None
    return Period(value.lower, value.upper - timedelta(days=1))


def _run_from_row(row: RunRow) -> ReconciliationRun:
    return ReconciliationRun(
        row.id,
        to_period(row.period),
        row.ruleset_version,
        RunStatus(row.status),
        row.started_at,
        row.finished_at,
    )


class SqlAlchemyRuns:
    def __init__(self, session: Session) -> None:
        self._session = session

    def lock(self, period: Period, ruleset_version: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"recon.run:{period.start}:{period.end}:{ruleset_version}"},
        )

    def find_live(self, period: Period, ruleset_version: str) -> ReconciliationRun | None:
        row = self._session.scalars(
            select(RunRow).where(
                RunRow.period == to_range(period),
                RunRow.ruleset_version == ruleset_version,
                RunRow.status != RunStatus.FAILED.value,
            )
        ).one_or_none()
        return None if row is None else _run_from_row(row)

    def add(self, run: ReconciliationRun) -> None:
        self._session.add(
            RunRow(
                id=run.id,
                period=to_range(run.period),
                ruleset_version=run.ruleset_version,
                status=run.status.value,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
        )

    def save(self, run: ReconciliationRun) -> None:
        self._session.execute(
            update(RunRow)
            .where(RunRow.id == run.id)
            .values(status=run.status.value, finished_at=run.finished_at)
        )


class SqlSourceRecords:
    """Reads every canonical record and remembers each one's row ID for the result writer."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.row_ids: dict[RecordRef, uuid.UUID] = {}

    def _rows(self, source: Source) -> list[Any]:
        rows = list(self._session.execute(text(_QUERIES[source])))
        self.row_ids.update({RecordRef(source, r.external_id): r.id for r in rows})
        return rows

    def snapshot(self, currency: str) -> Snapshot:
        conflicts = self._session.execute(
            text("SELECT DISTINCT record_type, external_id FROM ingestion.source_conflicts")
        )
        return Snapshot(
            currency=currency,
            orders=tuple(
                Order(r.external_id, r.placed_at, Money(r.amount_minor, r.currency))
                for r in self._rows(Source.ORDERS)
            ),
            payments=tuple(
                Payment(
                    r.external_id,
                    r.order_external_ref,
                    r.gateway,
                    Money(r.amount_minor, r.currency),
                    r.captured_at,
                    r.settlement_batch_ref,
                )
                for r in self._rows(Source.PAYMENTS)
            ),
            refunds=tuple(
                Refund(
                    r.external_id,
                    r.payment_external_ref,
                    r.gateway,
                    Money(r.amount_minor, r.currency),
                    r.refunded_at,
                    r.settlement_batch_ref,
                )
                for r in self._rows(Source.REFUNDS)
            ),
            fees=tuple(
                Fee(
                    r.external_id,
                    r.payment_external_ref,
                    r.gateway,
                    r.fee_type,
                    Money(r.amount_minor, r.currency),
                    r.settlement_batch_ref,
                )
                for r in self._rows(Source.FEES)
            ),
            settlements=tuple(
                Settlement(
                    r.external_id, r.gateway, r.batch_date, Money(r.net_amount_minor, r.currency)
                )
                for r in self._rows(Source.SETTLEMENTS)
            ),
            bank_transactions=tuple(
                BankTransaction(
                    r.external_id,
                    r.direction,
                    r.value_date,
                    Money(r.amount_minor, r.currency),
                    r.description,
                )
                for r in self._rows(Source.BANK_TRANSACTIONS)
            ),
            authorizations=tuple(
                Authorization(
                    r.external_id,
                    r.subject_kind,
                    r.subject_external_ref,
                    r.approved_at,
                    Money(r.max_amount_minor, r.currency),
                )
                for r in self._rows(Source.AUTHORIZATIONS)
            ),
            conflicts=tuple(SourceConflict(Source(t), e) for t, e in conflicts),
        )


class SqlAlchemyReferenceData:
    def __init__(self, session: Session) -> None:
        self._session = session

    def fee_schedules(self) -> tuple[FeeSchedule, ...]:
        rows = self._session.scalars(select(FeeScheduleRow).order_by(FeeScheduleRow.id))
        schedules = []
        for r in rows:
            assert r.valid_during.lower is not None  # CHECK: bounded below
            schedules.append(
                FeeSchedule(
                    r.gateway,
                    r.fee_type,
                    r.rate_bps,
                    Money(r.fixed_minor, r.currency),
                    r.valid_during.lower,
                    r.valid_during.upper,
                )
            )
        return tuple(schedules)

    def holidays(self) -> frozenset[date]:
        return frozenset(self._session.scalars(select(HolidayRow.day)))


class SqlAlchemyResults:
    def __init__(self, session: Session, sources: SqlSourceRecords) -> None:
        self._session = session
        self._sources = sources
        self._severity: dict[str, str] | None = None

    def _record_columns(self, ref: RecordRef) -> dict[str, uuid.UUID]:
        return {RECORD_COLUMN[ref.source]: self._sources.row_ids[ref]}

    def add_group(self, run_id: uuid.UUID, group_id: uuid.UUID, group: MatchGroup) -> None:
        self._session.execute(
            insert(MatchGroupRow).values(id=group_id, run_id=run_id, rule_code=group.rule_code)
        )
        self._session.execute(
            insert(MatchGroupMemberRow),
            [
                {
                    "group_id": group_id,
                    "run_id": run_id,
                    "role": m.role,
                    **self._record_columns(m.ref),
                }
                for m in sorted(group.members)
            ],
        )

    def add_discrepancy(
        self,
        run_id: uuid.UUID,
        discrepancy_id: uuid.UUID,
        discrepancy: Discrepancy,
        period: Period,
        detected_at: datetime,
    ) -> None:
        if self._severity is None:
            rows = self._session.execute(
                text("SELECT code, default_severity FROM ref.discrepancy_types")
            )
            self._severity = {code: severity for code, severity in rows}
        self._session.execute(
            insert(DiscrepancyRow).values(
                id=discrepancy_id,
                run_id=run_id,
                type=discrepancy.type.value,
                severity=self._severity[discrepancy.type.value],
                expected_minor=discrepancy.expected.amount_minor,
                actual_minor=discrepancy.actual.amount_minor,
                currency=discrepancy.actual.currency,
                fingerprint=discrepancy.fingerprint(period),
                status="detected",
                detected_at=detected_at,
            )
        )
        self._session.execute(
            insert(DiscrepancyRecordRow),
            [
                {"discrepancy_id": discrepancy_id, **self._record_columns(ref)}
                for ref in sorted(discrepancy.records)
            ],
        )


class SqlAlchemyReconciliationUnitOfWork:
    """One database transaction per ``with`` block; leaving it without ``commit`` rolls back."""

    runs: SqlAlchemyRuns
    sources: SqlSourceRecords
    reference: SqlAlchemyReferenceData
    results: SqlAlchemyResults

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.runs = SqlAlchemyRuns(self._session)
        self.sources = SqlSourceRecords(self._session)
        self.reference = SqlAlchemyReferenceData(self._session)
        self.results = SqlAlchemyResults(self._session, self.sources)
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
        self._session.add(
            OutboxRow(
                event_type=event.event_type,
                event_version=event.event_version,
                payload=event_payload(event),
                created_at=event.occurred_at,
            )
        )
