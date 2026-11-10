"""PostgreSQL persistence of the Ingestion context: mappers, repositories, unit of work."""

import dataclasses
import json
import uuid
from collections.abc import Collection
from datetime import date, datetime
from types import TracebackType
from typing import Self

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from recon.ingestion.adapters.outbound.orm import (
    AuthorizationRow,
    BankTransactionRow,
    DataSourceRow,
    FeeRow,
    ImportBatchErrorRow,
    ImportBatchRow,
    OrderRow,
    OutboxRow,
    PaymentRow,
    RawRecordRow,
    RefundRow,
    SettlementRow,
    SourceConflictRow,
)
from recon.ingestion.domain.batch import ImportBatch, RowError
from recon.ingestion.domain.records import (
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    RawRecord,
    RecordType,
    Refund,
    Settlement,
    SourceConflict,
    SourceRecord,
)
from recon.shared_kernel.events import DomainEvent

type RecordRow = (
    OrderRow
    | PaymentRow
    | RefundRow
    | FeeRow
    | SettlementRow
    | BankTransactionRow
    | AuthorizationRow
)

ROW_OF: dict[RecordType, type[RecordRow]] = {
    RecordType.ORDERS: OrderRow,
    RecordType.PAYMENTS: PaymentRow,
    RecordType.REFUNDS: RefundRow,
    RecordType.FEES: FeeRow,
    RecordType.SETTLEMENTS: SettlementRow,
    RecordType.BANK_TRANSACTIONS: BankTransactionRow,
    RecordType.AUTHORIZATIONS: AuthorizationRow,
}


def record_to_row(record: SourceRecord, raw_id: uuid.UUID, source_id: uuid.UUID) -> RecordRow:
    keys = {"id": uuid.uuid4(), "source_id": source_id, "raw_record_id": raw_id}
    match record:
        case Order():
            return OrderRow(
                **keys,
                external_id=record.external_id,
                customer_name=record.customer_name,
                customer_email=record.customer_email,
                amount_minor=record.total.amount_minor,
                currency=record.total.currency,
                status=record.status,
                placed_at=record.placed_at,
            )
        case Payment():
            return PaymentRow(
                **keys,
                external_id=record.external_id,
                order_external_ref=record.order_external_ref,
                gateway=record.gateway,
                amount_minor=record.amount.amount_minor,
                currency=record.amount.currency,
                captured_at=record.captured_at,
                settlement_batch_ref=record.settlement_batch_ref,
            )
        case Refund():
            return RefundRow(
                **keys,
                external_id=record.external_id,
                payment_external_ref=record.payment_external_ref,
                gateway=record.gateway,
                amount_minor=record.amount.amount_minor,
                currency=record.amount.currency,
                refunded_at=record.refunded_at,
                settlement_batch_ref=record.settlement_batch_ref,
            )
        case Fee():
            return FeeRow(
                **keys,
                external_id=record.external_id,
                payment_external_ref=record.payment_external_ref,
                gateway=record.gateway,
                fee_type=record.fee_type,
                amount_minor=record.amount.amount_minor,
                currency=record.amount.currency,
                settlement_batch_ref=record.settlement_batch_ref,
            )
        case Settlement():
            return SettlementRow(
                **keys,
                external_id=record.external_id,
                gateway=record.gateway,
                batch_date=record.batch_date,
                net_amount_minor=record.net_amount.amount_minor,
                currency=record.net_amount.currency,
            )
        case BankTransaction():
            return BankTransactionRow(
                **keys,
                external_id=record.external_id,
                account_ref=record.account_ref,
                direction=record.direction,
                value_date=record.value_date,
                amount_minor=record.amount.amount_minor,
                currency=record.amount.currency,
                description=record.description,
            )
        case Authorization():
            return AuthorizationRow(
                **keys,
                external_id=record.external_id,
                subject_kind=record.subject_kind,
                subject_external_ref=record.subject_external_ref,
                approved_by=record.approved_by,
                approved_at=record.approved_at,
                max_amount_minor=record.max_amount.amount_minor,
                currency=record.max_amount.currency,
            )


def _raw_from_row(row: RawRecordRow, source: str) -> RawRecord:
    return RawRecord(row.id, row.batch_id, source, row.line_no, row.payload, row.payload_sha256)


def _json_value(value: object) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def event_payload(event: DomainEvent) -> dict[str, object]:
    payload: dict[str, object] = json.loads(
        json.dumps(dataclasses.asdict(event), default=_json_value)
    )
    return payload


class _Sources:
    """Data sources are reference rows seeded by migration; names are their stable identity."""

    def __init__(self, session: Session) -> None:
        rows = session.execute(select(DataSourceRow.name, DataSourceRow.id)).all()
        self.id_of = {name: source_id for name, source_id in rows}


class SqlAlchemyImportBatches:
    def __init__(self, session: Session, sources: _Sources) -> None:
        self._session = session
        self._sources = sources

    def lock_source(self, source: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"ingestion.source:{source}"},
        )

    def get_by_file(self, source: str, file_sha256: str) -> ImportBatch | None:
        row = self._session.scalars(
            select(ImportBatchRow).where(
                ImportBatchRow.source_id == self._sources.id_of[source],
                ImportBatchRow.file_sha256 == file_sha256,
            )
        ).one_or_none()
        if row is None:
            return None
        errors = self._session.scalars(
            select(ImportBatchErrorRow)
            .where(ImportBatchErrorRow.batch_id == row.id)
            .order_by(ImportBatchErrorRow.ordinal)
        )
        return ImportBatch(
            id=row.id,
            source=source,
            record_type=RecordType(row.record_type),
            file_name=row.file_name,
            file_sha256=row.file_sha256,
            status=row.status,  # type: ignore[arg-type]  # the CHECK constraint bounds it
            started_at=row.started_at,
            row_count=row.row_count,
            errors=tuple(RowError(row.file_name, e.line_no, e.field, e.message) for e in errors),
            finished_at=row.finished_at,
        )

    def add(self, batch: ImportBatch) -> None:
        self._session.add(
            ImportBatchRow(
                id=batch.id,
                source_id=self._sources.id_of[batch.source],
                record_type=batch.record_type.value,
                file_name=batch.file_name,
                file_sha256=batch.file_sha256,
                status=batch.status,
                row_count=batch.row_count,
                started_at=batch.started_at,
                finished_at=batch.finished_at,
            )
        )
        self._session.flush()

    def save(self, batch: ImportBatch) -> None:
        row = self._session.get_one(ImportBatchRow, batch.id)
        row.status = batch.status
        row.row_count = batch.row_count
        row.finished_at = batch.finished_at
        stored = self._session.scalars(
            select(ImportBatchErrorRow.ordinal).where(ImportBatchErrorRow.batch_id == batch.id)
        ).all()
        for ordinal, error in enumerate(batch.errors[len(stored) :], len(stored) + 1):
            self._session.add(
                ImportBatchErrorRow(
                    batch_id=batch.id,
                    ordinal=ordinal,
                    line_no=error.line_no,
                    field=error.field,
                    message=error.message,
                )
            )
        self._session.flush()


class SqlAlchemySourceRecords:
    def __init__(self, session: Session, sources: _Sources) -> None:
        self._session = session
        self._sources = sources
        self._raws_pending = False

    def _flush_raws(self) -> None:
        # The ORM has no relationships, so it does not order inserts by foreign key: raw records
        # must reach the database before the rows that point at them.
        if self._raws_pending:
            self._session.flush()
            self._raws_pending = False

    def add_raw(self, raw: RawRecord) -> None:
        self._raws_pending = True
        self._session.add(
            RawRecordRow(
                id=raw.id,
                batch_id=raw.batch_id,
                source_id=self._sources.id_of[raw.source],
                line_no=raw.line_no,
                payload=raw.payload,
                payload_sha256=raw.payload_sha256,
            )
        )

    def add(self, record: SourceRecord, raw: RawRecord) -> None:
        self._flush_raws()
        self._session.add(record_to_row(record, raw.id, self._sources.id_of[raw.source]))

    def find_canonical_raws(
        self, source: str, record_type: RecordType, external_ids: Collection[str]
    ) -> dict[str, RawRecord]:
        table = ROW_OF[record_type]
        rows = self._session.execute(
            select(table.external_id, RawRecordRow)
            .join(table, table.raw_record_id == RawRecordRow.id)
            .where(
                table.source_id == self._sources.id_of[source],
                table.external_id.in_(external_ids),
            )
        ).all()
        return {external_id: _raw_from_row(raw, source) for external_id, raw in rows}

    def find_conflict_payloads(
        self, source: str, record_type: RecordType, external_ids: Collection[str]
    ) -> set[tuple[str, str]]:
        rows = self._session.execute(
            select(SourceConflictRow.external_id, SourceConflictRow.incoming_payload_sha256).where(
                SourceConflictRow.source_id == self._sources.id_of[source],
                SourceConflictRow.record_type == record_type.value,
                SourceConflictRow.external_id.in_(external_ids),
            )
        ).all()
        return {(external_id, sha) for external_id, sha in rows}

    def add_conflict(self, conflict: SourceConflict) -> None:
        self._flush_raws()
        self._session.add(
            SourceConflictRow(
                id=conflict.id,
                source_id=self._sources.id_of[conflict.source],
                record_type=conflict.record_type.value,
                external_id=conflict.external_id,
                existing_raw_record_id=conflict.existing_raw_record_id,
                incoming_raw_record_id=conflict.incoming_raw_record_id,
                incoming_payload_sha256=conflict.incoming_payload_sha256,
                detected_at=conflict.detected_at,
            )
        )


class SqlAlchemyIngestionUnitOfWork:
    """One database transaction per ``with`` block; leaving it without ``commit`` rolls back."""

    batches: SqlAlchemyImportBatches
    records: SqlAlchemySourceRecords

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        sources = _Sources(self._session)
        self.batches = SqlAlchemyImportBatches(self._session, sources)
        self.records = SqlAlchemySourceRecords(self._session, sources)
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
