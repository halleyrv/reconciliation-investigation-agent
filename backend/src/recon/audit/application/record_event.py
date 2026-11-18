from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

from recon.audit.domain.chain import AuditRecord, ChainedEntry, entry_hash, first_broken


class AuditLog(Protocol):
    def lock(self) -> None:
        """Serialize appends until the transaction ends, so the chain stays linear."""
        ...

    def contains(self, source: str, source_event_id: int) -> bool: ...

    def last_sha256(self) -> str | None: ...

    def append(self, record: AuditRecord, prev_sha256: str | None, sha256: str) -> None: ...

    def entries(self) -> Iterator[ChainedEntry]:
        """Every entry in chain order."""
        ...


class AuditUnitOfWork(Protocol):
    """Transaction boundary of the Audit context; it writes no events of its own."""

    @property
    def log(self) -> AuditLog: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class RecordEvent:
    """Append one event to the chain. Idempotent by its source outbox row."""

    def __init__(self, uow: AuditUnitOfWork) -> None:
        self._uow = uow

    def __call__(self, record: AuditRecord) -> bool:
        with self._uow as uow:
            uow.log.lock()
            if uow.log.contains(record.source, record.source_event_id):
                return False
            prev = uow.log.last_sha256()
            uow.log.append(record, prev, entry_hash(record, prev))
            uow.commit()
            return True


@dataclass(frozen=True, slots=True)
class ChainReport:
    entries: int
    first_broken: int | None


class VerifyChain:
    def __init__(self, uow: AuditUnitOfWork) -> None:
        self._uow = uow

    def __call__(self) -> ChainReport:
        with self._uow as uow:
            entries = list(uow.log.entries())
        return ChainReport(len(entries), first_broken(entries))
