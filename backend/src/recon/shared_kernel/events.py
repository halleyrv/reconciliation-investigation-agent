from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base of every domain event. Subclasses are frozen dataclasses with plain fields."""

    occurred_at: datetime
    event_version: ClassVar[int] = 1

    @property
    def event_type(self) -> str:
        return type(self).__name__
