"""In-memory unit of work for application tests."""

import copy
from collections.abc import Iterator
from types import TracebackType
from typing import Self

from recon.audit.domain.chain import AuditRecord, ChainedEntry


class _Log:
    def __init__(self, entries: list[ChainedEntry]) -> None:
        self._entries = entries

    def lock(self) -> None:
        pass  # one thread: nothing to serialize

    def contains(self, source: str, source_event_id: int) -> bool:
        return any(
            (e.record.source, e.record.source_event_id) == (source, source_event_id)
            for e in self._entries
        )

    def last_sha256(self) -> str | None:
        return self._entries[-1].sha256 if self._entries else None

    def append(self, record: AuditRecord, prev_sha256: str | None, sha256: str) -> None:
        self._entries.append(ChainedEntry(len(self._entries) + 1, record, prev_sha256, sha256))

    def entries(self) -> Iterator[ChainedEntry]:
        return iter(self._entries)


class InMemoryAuditUnitOfWork:
    """``entries`` is what a later transaction sees; a block without ``commit`` leaves it."""

    log: _Log

    def __init__(self) -> None:
        self.entries: list[ChainedEntry] = []

    def __enter__(self) -> Self:
        self._working = copy.deepcopy(self.entries)
        self.log = _Log(self._working)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del self._working

    def commit(self) -> None:
        self.entries = copy.deepcopy(self._working)
