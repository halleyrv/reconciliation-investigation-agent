import dataclasses
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar

from recon.shared_kernel.actor import Actor


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base of every domain event. Subclasses are frozen dataclasses with plain fields."""

    occurred_at: datetime
    event_version: ClassVar[int] = 1
    # (aggregate type, name of the field holding its ID): the audit trail indexes events by it
    aggregate: ClassVar[tuple[str, str]]

    @property
    def event_type(self) -> str:
        return type(self).__name__


def _json_value(value: object) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def event_payload(event: DomainEvent) -> dict[str, object]:
    """The event as JSON-ready values, the form every context's outbox stores."""
    payload: dict[str, object] = json.loads(
        json.dumps(dataclasses.asdict(event), default=_json_value)
    )
    return payload


def outbox_columns(event: DomainEvent, actor: Actor) -> dict[str, object]:
    """The outbox row of an event, the same in every context."""
    aggregate_type, id_field = event.aggregate
    aggregate_id = getattr(event, id_field)
    assert isinstance(aggregate_id, uuid.UUID)
    return {
        "event_type": event.event_type,
        "event_version": event.event_version,
        "payload": event_payload(event),
        "created_at": event.occurred_at,
        "actor_type": actor.type.value,
        "actor_id": actor.id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
    }


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """An outbox row as the in-process dispatcher hands it to event handlers."""

    outbox: str
    id: int
    event_type: str
    event_version: int
    payload: dict[str, object]
    created_at: datetime
    actor: Actor
    aggregate_type: str | None
    aggregate_id: uuid.UUID | None
