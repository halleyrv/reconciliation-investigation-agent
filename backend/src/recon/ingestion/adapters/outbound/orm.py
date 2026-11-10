"""SQLAlchemy ORM models of the ``ingestion`` schema (ADR-0004). Constraints live in the
migrations; these classes only name the columns the adapter reads and writes."""

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="ingestion")
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, object]: JSONB,
        datetime: DateTime(timezone=True),
    }


class DataSourceRow(Base):
    __tablename__ = "data_sources"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str]
    name: Mapped[str]


class ImportBatchRow(Base):
    __tablename__ = "import_batches"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID]
    record_type: Mapped[str]
    file_name: Mapped[str]
    file_sha256: Mapped[str]
    status: Mapped[str]
    row_count: Mapped[int]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]


class ImportBatchErrorRow(Base):
    __tablename__ = "import_batch_errors"
    batch_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    line_no: Mapped[int]
    field: Mapped[str]
    message: Mapped[str]


class RawRecordRow(Base):
    __tablename__ = "raw_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID]
    source_id: Mapped[uuid.UUID]
    line_no: Mapped[int]
    payload: Mapped[dict[str, object]]
    payload_sha256: Mapped[str]


class _RecordColumns:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID]
    external_id: Mapped[str]
    raw_record_id: Mapped[uuid.UUID]


class OrderRow(_RecordColumns, Base):
    __tablename__ = "orders"
    customer_name: Mapped[str]
    customer_email: Mapped[str]
    amount_minor: Mapped[int]
    currency: Mapped[str]
    status: Mapped[str]
    placed_at: Mapped[datetime]


class PaymentRow(_RecordColumns, Base):
    __tablename__ = "payments"
    order_external_ref: Mapped[str]
    gateway: Mapped[str]
    amount_minor: Mapped[int]
    currency: Mapped[str]
    captured_at: Mapped[datetime]
    settlement_batch_ref: Mapped[str]


class RefundRow(_RecordColumns, Base):
    __tablename__ = "refunds"
    payment_external_ref: Mapped[str]
    gateway: Mapped[str]
    amount_minor: Mapped[int]
    currency: Mapped[str]
    refunded_at: Mapped[datetime]
    settlement_batch_ref: Mapped[str]


class FeeRow(_RecordColumns, Base):
    __tablename__ = "fees"
    payment_external_ref: Mapped[str]
    gateway: Mapped[str]
    fee_type: Mapped[str]
    amount_minor: Mapped[int]
    currency: Mapped[str]
    settlement_batch_ref: Mapped[str]


class SettlementRow(_RecordColumns, Base):
    __tablename__ = "settlements"
    gateway: Mapped[str]
    batch_date: Mapped[date]
    net_amount_minor: Mapped[int]
    currency: Mapped[str]


class BankTransactionRow(_RecordColumns, Base):
    __tablename__ = "bank_transactions"
    account_ref: Mapped[str]
    direction: Mapped[str]
    value_date: Mapped[date]
    amount_minor: Mapped[int]
    currency: Mapped[str]
    description: Mapped[str]


class AuthorizationRow(_RecordColumns, Base):
    __tablename__ = "authorizations"
    subject_kind: Mapped[str]
    subject_external_ref: Mapped[str]
    approved_by: Mapped[str]
    approved_at: Mapped[datetime]
    max_amount_minor: Mapped[int]
    currency: Mapped[str]


class SourceConflictRow(Base):
    __tablename__ = "source_conflicts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID]
    record_type: Mapped[str]
    external_id: Mapped[str]
    existing_raw_record_id: Mapped[uuid.UUID]
    incoming_raw_record_id: Mapped[uuid.UUID]
    incoming_payload_sha256: Mapped[str]
    detected_at: Mapped[datetime]


class OutboxRow(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str]
    event_version: Mapped[int]
    payload: Mapped[dict[str, object]]
    created_at: Mapped[datetime]
    published_at: Mapped[datetime | None]
