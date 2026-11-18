"""Audit is a conformist consumer of every context's events (bounded-contexts.md)."""

from collections.abc import Callable

from recon.audit.application.record_event import RecordEvent
from recon.audit.domain.chain import AuditRecord
from recon.shared_kernel.events import OutboxMessage


def record_every_event(record_event: RecordEvent) -> Callable[[OutboxMessage], None]:
    def handle(message: OutboxMessage) -> None:
        record_event(
            AuditRecord(
                source=message.outbox,
                source_event_id=message.id,
                occurred_at=message.created_at,
                actor=message.actor,
                aggregate_type=message.aggregate_type,
                aggregate_id=message.aggregate_id,
                event_type=message.event_type,
                event_version=message.event_version,
                payload=message.payload,
            )
        )

    return handle
