import dataclasses
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base of every domain event. Subclasses are frozen dataclasses with plain fields."""

    occurred_at: datetime
    event_version: ClassVar[int] = 1

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
