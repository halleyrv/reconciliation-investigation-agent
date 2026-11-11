"""SQLAlchemy ORM models of the ``recon`` schema (ADR-0004). Constraints live in migration 0002;
these classes only name the columns the adapter reads and writes."""

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, Range
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="recon")
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, object]: JSONB,
        datetime: DateTime(timezone=True),
        Range[date]: DATERANGE,
    }


class FeeScheduleRow(Base):
    __tablename__ = "fee_schedules"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    gateway: Mapped[str]
    fee_type: Mapped[str]
    rate_bps: Mapped[int]
    fixed_minor: Mapped[int]
    currency: Mapped[str]
    valid_during: Mapped[Range[date]]
    policy_document_id: Mapped[uuid.UUID | None]


class HolidayRow(Base):
    __tablename__ = "holidays"
    day: Mapped[date] = mapped_column(primary_key=True)


class CalendarYearRow(Base):
    __tablename__ = "calendar_years"
    year: Mapped[int] = mapped_column(primary_key=True)


class RunRow(Base):
    __tablename__ = "reconciliation_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    period: Mapped[Range[date]]
    ruleset_version: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]


class MatchGroupRow(Base):
    __tablename__ = "match_groups"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID]
    rule_code: Mapped[str]


class _OneRecord:
    """The exclusive-arc record columns shared by members and discrepancy records."""

    order_id: Mapped[uuid.UUID | None]
    payment_id: Mapped[uuid.UUID | None]
    refund_id: Mapped[uuid.UUID | None]
    fee_id: Mapped[uuid.UUID | None]
    settlement_id: Mapped[uuid.UUID | None]
    bank_transaction_id: Mapped[uuid.UUID | None]


class MatchGroupMemberRow(_OneRecord, Base):
    __tablename__ = "match_group_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[uuid.UUID]
    run_id: Mapped[uuid.UUID]
    role: Mapped[str]


class DiscrepancyRow(Base):
    __tablename__ = "discrepancies"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID]
    type: Mapped[str]
    severity: Mapped[str]
    expected_minor: Mapped[int]
    actual_minor: Mapped[int]
    currency: Mapped[str]
    fingerprint: Mapped[str]
    status: Mapped[str]
    detected_at: Mapped[datetime]


class DiscrepancyRecordRow(_OneRecord, Base):
    __tablename__ = "discrepancy_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    discrepancy_id: Mapped[uuid.UUID]
    authorization_id: Mapped[uuid.UUID | None]


class OutboxRow(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str]
    event_version: Mapped[int]
    payload: Mapped[dict[str, object]]
    created_at: Mapped[datetime]
    published_at: Mapped[datetime | None]
    actor_type: Mapped[str]
    actor_id: Mapped[str]
    aggregate_type: Mapped[str | None]
    aggregate_id: Mapped[uuid.UUID | None]
