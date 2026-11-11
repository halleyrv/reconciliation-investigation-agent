"""Who caused a change (ADR-0018). Authentication does not exist yet, so a ``user`` actor is
the ID a client claims; ``system`` actors are named after the command or handler."""

from dataclasses import dataclass
from enum import StrEnum


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Actor:
    type: ActorType
    id: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("an actor needs a non-empty ID")

    @classmethod
    def system(cls, name: str) -> Actor:
        return cls(ActorType.SYSTEM, name)
