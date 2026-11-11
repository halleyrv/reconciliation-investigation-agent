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
    CalendarYearRow,
    DiscrepancyRecordRow,
    DiscrepancyRow,
    FeeScheduleRow,
    HolidayRow,
    MatchGroupMemberRow,
    MatchGroupRow,
    OutboxRow,
    RunRow,
)
from recon.reconciliation.application.evaluation import Finding, Link
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
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.events import DomainEvent, outbox_columns
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
            # Per ruleset, not per period: overlapping periods must see each other's runs.
            {"key": f"recon.run:{ruleset_version}"},
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

    def find_overlapping(self, period: Period, ruleset_version: str) -> ReconciliationRun | None:
        row = self._session.scalars(
            select(RunRow)
            .where(
                RunRow.period.overlaps(to_range(period)),
                RunRow.period != to_range(period),
                RunRow.ruleset_version == ruleset_version,
                RunRow.status != RunStatus.FAILED.value,
            )
            .order_by(RunRow.started_at)
            .limit(1)
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

    def latest_bank_date(self) -> date | None:
        latest: date | None = self._session.execute(
            text("SELECT max(value_date) FROM ingestion.bank_transactions")
        ).scalar_one()
        return latest

    def snapshot(self, currency: str) -> Snapshot:
        # One consistent view of every table: an import committing between these queries must
        # not mix into a run (phase review M2). PostgreSQL refuses this unless it is the
        # transaction's first statement, so a misuse fails loudly. Only here: the run-start
        # transaction must stay READ COMMITTED to see a run committed while it waited on the lock.
        self._session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
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

    def add_fee_schedule(self, schedule_id: uuid.UUID, schedule: FeeSchedule) -> None:
        self._session.execute(
            insert(FeeScheduleRow).values(
                id=schedule_id,
                gateway=schedule.gateway,
                fee_type=schedule.fee_type,
                rate_bps=schedule.rate_bps,
                fixed_minor=schedule.fixed.amount_minor,
                currency=schedule.fixed.currency,
                valid_during=Range(schedule.valid_from, schedule.valid_until, bounds="[)"),
            )
        )

    def add_holiday(self, day: date) -> None:
        self._session.execute(insert(HolidayRow).values(day=day))

    def calendar_years(self) -> frozenset[int]:
        return frozenset(self._session.scalars(select(CalendarYearRow.year)))

    def add_calendar_year(self, year: int) -> None:
        self._session.execute(insert(CalendarYearRow).values(year=year))


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


_RECORD_JOINS = " ".join(
    f"LEFT JOIN ingestion.{table} {alias} ON {alias}.id = r.{column}"
    for alias, (table, column) in {
        "o": ("orders", "order_id"),
        "p": ("payments", "payment_id"),
        "rf": ("refunds", "refund_id"),
        "f": ("fees", "fee_id"),
        "s": ("settlements", "settlement_id"),
        "b": ("bank_transactions", "bank_transaction_id"),
        "a": ("authorizations", "authorization_id"),
    }.items()
)
_FINDINGS = f"""
SELECT d.id, d.type, d.delta_minor,
       CASE WHEN o.id IS NOT NULL THEN 'orders' WHEN p.id IS NOT NULL THEN 'payments'
            WHEN rf.id IS NOT NULL THEN 'refunds' WHEN f.id IS NOT NULL THEN 'fees'
            WHEN s.id IS NOT NULL THEN 'settlements' WHEN b.id IS NOT NULL THEN 'bank_transactions'
            WHEN a.id IS NOT NULL THEN 'authorizations' END AS source,
       COALESCE(o.external_id, p.external_id, rf.external_id, f.external_id, s.external_id,
                b.external_id, a.external_id) AS external_id
FROM recon.discrepancies d JOIN recon.discrepancy_records r ON r.discrepancy_id = d.id
{_RECORD_JOINS}
WHERE d.run_id = :run_id
"""
_LINKS = """
SELECT o.external_id, p.external_id, s.external_id, b.external_id
FROM recon.match_group_members mo
JOIN ingestion.orders o ON o.id = mo.order_id
JOIN recon.match_group_members mp ON mp.group_id = mo.group_id AND mp.payment_id IS NOT NULL
JOIN ingestion.payments p ON p.id = mp.payment_id AND p.order_external_ref = o.external_id
JOIN recon.match_group_members ms ON ms.group_id = mo.group_id AND ms.settlement_id IS NOT NULL
JOIN ingestion.settlements s ON s.id = ms.settlement_id
JOIN recon.match_group_members mb
    ON mb.group_id = mo.group_id AND mb.bank_transaction_id IS NOT NULL
JOIN ingestion.bank_transactions b ON b.id = mb.bank_transaction_id
WHERE mo.run_id = :run_id
"""


class SqlRunOutputs:
    def __init__(self, session: Session) -> None:
        self._session = session

    def findings(self, run_id: uuid.UUID) -> list[Finding]:
        grouped: dict[uuid.UUID, tuple[str, int, set[tuple[str, str]]]] = {}
        for row in self._session.execute(text(_FINDINGS), {"run_id": run_id}):
            if row.source is None:  # a record column this query does not join yet
                raise ValueError(f"discrepancy {row.id} names a record of an unknown type")
            _, _, records = grouped.setdefault(row.id, (row.type, row.delta_minor, set()))
            records.add((row.source, row.external_id))
        return [Finding(t, frozenset(records), delta) for t, delta, records in grouped.values()]

    def links(self, run_id: uuid.UUID) -> set[Link]:
        rows = self._session.execute(text(_LINKS), {"run_id": run_id})
        return {Link(*row) for row in rows}


class SqlAlchemyReconciliationUnitOfWork:
    """One database transaction per ``with`` block; leaving it without ``commit`` rolls back."""

    runs: SqlAlchemyRuns
    sources: SqlSourceRecords
    reference: SqlAlchemyReferenceData
    results: SqlAlchemyResults
    outputs: SqlRunOutputs

    def __init__(self, session_factory: sessionmaker[Session], *, actor: Actor) -> None:
        self._session_factory = session_factory
        self._actor = actor  # stamped on every event this unit of work writes (ADR-0018)

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.runs = SqlAlchemyRuns(self._session)
        self.sources = SqlSourceRecords(self._session)
        self.reference = SqlAlchemyReferenceData(self._session)
        self.results = SqlAlchemyResults(self._session, self.sources)
        self.outputs = SqlRunOutputs(self._session)
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
