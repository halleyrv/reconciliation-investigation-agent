"""In-process dispatch of every context's outbox (AS4, ADR-0001).

Each event is delivered at least once: its handlers run, then the row is marked published.
A crash in between delivers it again, so handlers must be idempotent. A failing handler
leaves its row unpublished for the next drain and does not stop the other rows.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from recon.audit.adapters.inbound.events import record_every_event
from recon.audit.adapters.outbound.sql import SqlAlchemyAuditUnitOfWork
from recon.audit.application.record_event import RecordEvent
from recon.investigation.adapters.inbound.events import on_discrepancy_detected
from recon.investigation.adapters.outbound.sql import SqlAlchemyInvestigationUnitOfWork
from recon.investigation.application.open_case import OpenCase
from recon.shared_kernel.actor import Actor, ActorType
from recon.shared_kernel.events import OutboxMessage
from recon.shared_kernel.ports import SystemClock, UuidIdGenerator

Handler = Callable[[OutboxMessage], None]
OUTBOXES = ("ingestion.outbox", "recon.outbox", "investigation.outbox")


@dataclass(frozen=True, slots=True)
class FailedDelivery:
    outbox: str
    event_id: int
    event_type: str
    error: str


@dataclass(slots=True)
class DrainResult:
    delivered: int = 0
    failed: list[FailedDelivery] = field(default_factory=list)


class OutboxRelay:
    def __init__(
        self,
        engine: Engine,
        handlers: Mapping[str, Sequence[Handler]],
        every: Sequence[Handler] = (),
    ) -> None:
        """``every`` runs for every event (the audit trail), then ``handlers`` of its type."""
        self._engine = engine
        self._handlers = handlers
        self._every = every

    @property
    def event_types(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def drain(self) -> DrainResult:
        """Deliver every unpublished event, oldest first per outbox."""
        result = DrainResult()
        for outbox in OUTBOXES:
            after = 0
            while (event_id := self._deliver_next(outbox, after, result)) is not None:
                after = event_id
        return result

    def _deliver_next(self, outbox: str, after: int, result: DrainResult) -> int | None:
        with self._engine.begin() as connection:
            # SKIP LOCKED: a concurrent drain takes the next row instead of waiting on this one
            row = connection.execute(
                text(
                    "SELECT id, event_type, event_version, payload, created_at, actor_type,"
                    f" actor_id, aggregate_type, aggregate_id FROM {outbox}"  # OUTBOXES names only
                    " WHERE published_at IS NULL AND id > :after"
                    " ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ),
                {"after": after},
            ).first()
            if row is None:
                return None
            try:
                message = OutboxMessage(
                    outbox=outbox,
                    id=row.id,
                    event_type=row.event_type,
                    event_version=row.event_version,
                    payload=row.payload,
                    created_at=row.created_at,
                    actor=Actor(ActorType(row.actor_type), row.actor_id),
                    aggregate_type=row.aggregate_type,
                    aggregate_id=row.aggregate_id,
                )
                # the audit trail first, so a failing business handler cannot hide an event
                for handle in (*self._every, *self._handlers.get(row.event_type, ())):
                    handle(message)
            except Exception as exc:  # kept for the next drain, reported
                result.failed.append(FailedDelivery(outbox, row.id, row.event_type, repr(exc)))
                return int(row.id)
            connection.execute(
                text(f"UPDATE {outbox} SET published_at = now() WHERE id = :id"),
                {"id": row.id},
            )
            result.delivered += 1
            return int(row.id)


def default_relay(engine: Engine) -> OutboxRelay:
    sessions = sessionmaker(engine)
    open_case = OpenCase(
        SqlAlchemyInvestigationUnitOfWork(
            sessions, actor=Actor.system("open-case-on-discrepancy-detected")
        ),
        SystemClock(),
        UuidIdGenerator(),
    )
    return OutboxRelay(
        engine,
        {"DiscrepancyDetected": [on_discrepancy_detected(open_case)]},
        every=[record_every_event(RecordEvent(SqlAlchemyAuditUnitOfWork(sessions)))],
    )


def dispatch(relay: OutboxRelay) -> list[str]:
    """Deliver the events a successful command or request wrote, and return a warning per
    problem. Delivery problems never fail the caller: the events stay in their outbox and the
    next drain retries them."""
    try:
        failures = relay.drain().failed
    except SQLAlchemyError as exc:
        return [f"events not dispatched, retried by the next command: {exc}"]
    return [
        f"event {f.event_id} ({f.event_type}) of {f.outbox} not delivered, retried by the next"
        f" command: {f.error}"
        for f in failures
    ]
