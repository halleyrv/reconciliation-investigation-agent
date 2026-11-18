"""PostgreSQL persistence of the Audit context: ``audit.events``, append-only (migration 0004)."""

from collections.abc import Iterator
from types import TracebackType
from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import bindparam

from recon.audit.domain.chain import AuditRecord, ChainedEntry
from recon.shared_kernel.actor import Actor, ActorType

_COLUMNS = (
    "source, source_event_id, occurred_at, actor_type, actor_id, aggregate_type, aggregate_id,"
    " event_type, event_version, payload, prev_sha256, sha256"
)


def _entry(row: Any) -> ChainedEntry:
    record = AuditRecord(
        source=row.source,
        source_event_id=row.source_event_id,
        occurred_at=row.occurred_at,
        actor=Actor(ActorType(row.actor_type), row.actor_id),
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        event_version=row.event_version,
        payload=row.payload,
    )
    return ChainedEntry(row.id, record, row.prev_sha256, row.sha256)


class SqlAuditLog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def lock(self) -> None:
        self._session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('audit', 0))"))

    def contains(self, source: str, source_event_id: int) -> bool:
        return (
            self._session.execute(
                text("SELECT 1 FROM audit.events WHERE source = :s AND source_event_id = :i"),
                {"s": source, "i": source_event_id},
            ).first()
            is not None
        )

    def last_sha256(self) -> str | None:
        sha: str | None = self._session.execute(
            text("SELECT sha256 FROM audit.events ORDER BY id DESC LIMIT 1")
        ).scalar_one_or_none()
        return sha

    def append(self, record: AuditRecord, prev_sha256: str | None, sha256: str) -> None:
        self._session.execute(
            text(
                f"INSERT INTO audit.events ({_COLUMNS}) VALUES (:source, :source_event_id,"
                " :occurred_at, :actor_type, :actor_id, :aggregate_type, :aggregate_id,"
                " :event_type, :event_version, :payload, :prev_sha256, :sha256)"
            ).bindparams(bindparam("payload", type_=JSONB)),
            {
                "source": record.source,
                "source_event_id": record.source_event_id,
                "occurred_at": record.occurred_at,
                "actor_type": record.actor.type.value,
                "actor_id": record.actor.id,
                "aggregate_type": record.aggregate_type,
                "aggregate_id": record.aggregate_id,
                "event_type": record.event_type,
                "event_version": record.event_version,
                "payload": record.payload,
                "prev_sha256": prev_sha256,
                "sha256": sha256,
            },
        )

    def entries(self) -> Iterator[ChainedEntry]:
        rows = self._session.execute(text(f"SELECT id, {_COLUMNS} FROM audit.events ORDER BY id"))
        return (_entry(row) for row in rows)


class SqlAlchemyAuditUnitOfWork:
    """One database transaction per ``with`` block; leaving it without ``commit`` rolls back."""

    log: SqlAuditLog

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.log = SqlAuditLog(self._session)
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
