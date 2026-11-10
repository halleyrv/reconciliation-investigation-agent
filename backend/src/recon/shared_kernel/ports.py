"""Ports every context shares, with their stdlib implementations."""

import itertools
import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol, Self

from recon.shared_kernel.events import DomainEvent


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> uuid.UUID: ...


class UnitOfWork(Protocol):
    """Transaction boundary. Leaving the block without ``commit`` discards every change."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def add_event(self, event: DomainEvent) -> None:
        """Write the event to the context's outbox, in the same transaction."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class UuidIdGenerator:
    def new(self) -> uuid.UUID:
        return uuid.uuid4()


class SequenceIdGenerator:
    """Deterministic IDs for tests: 00000000-0000-0000-0000-000000000001, ...02, ..."""

    def __init__(self) -> None:
        self._next = itertools.count(1)

    def new(self) -> uuid.UUID:
        return uuid.UUID(int=next(self._next))
