"""SQLAlchemy ORM models of the ``investigation`` schema (ADR-0004). Constraints live in
migration 0003; these classes only name the columns the adapter reads and writes."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="investigation")
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, object]: JSONB,
        datetime: DateTime(timezone=True),
    }


class CaseRow(Base):
    __tablename__ = "cases"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    discrepancy_id: Mapped[uuid.UUID]
    status: Mapped[str]
    priority: Mapped[str]
    assignee_id: Mapped[str | None]
    opened_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]
    version: Mapped[int]


class OutboxRow(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str]
    event_version: Mapped[int]
    payload: Mapped[dict[str, object]]
    created_at: Mapped[datetime]
    published_at: Mapped[datetime | None]
