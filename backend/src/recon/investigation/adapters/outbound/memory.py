"""In-memory unit of work for application tests. It keeps one case per discrepancy."""

import copy
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from recon.investigation.application.ports import DiscrepancyView
from recon.investigation.domain.case import ReconciliationCase
from recon.shared_kernel.events import DomainEvent


@dataclass
class State:
    cases: dict[uuid.UUID, ReconciliationCase] = field(default_factory=dict)
    events: list[DomainEvent] = field(default_factory=list)


class _Cases:
    def __init__(self, state: State, opened_concurrently: ReconciliationCase | None) -> None:
        self._state = state
        self._concurrent = opened_concurrently

    def find_by_discrepancy(self, discrepancy_id: uuid.UUID) -> ReconciliationCase | None:
        if self._concurrent is not None:
            # another caller commits its case right after this read
            self._state.cases[self._concurrent.id], self._concurrent = self._concurrent, None
            return None
        return next(
            (c for c in self._state.cases.values() if c.discrepancy_id == discrepancy_id), None
        )

    def add(self, case: ReconciliationCase) -> bool:
        if self.find_by_discrepancy(case.discrepancy_id) is not None:
            return False
        self._state.cases[case.id] = case
        return True


class _Discrepancies:
    def __init__(self, views: Iterable[DiscrepancyView]) -> None:
        self._views = {v.id: v for v in views}

    def get(self, discrepancy_id: uuid.UUID) -> DiscrepancyView | None:
        return self._views.get(discrepancy_id)


class InMemoryInvestigationUnitOfWork:
    """``committed`` is what a later transaction sees; a block without ``commit`` leaves it."""

    cases: _Cases

    def __init__(
        self,
        discrepancies: Iterable[DiscrepancyView] = (),
        opened_concurrently: ReconciliationCase | None = None,
    ) -> None:
        self.committed = State()
        self.discrepancies = _Discrepancies(discrepancies)
        self.opened_concurrently = opened_concurrently  # test hook, used by the next transaction

    def __enter__(self) -> Self:
        self._working = copy.deepcopy(self.committed)
        self.cases = _Cases(self._working, self.opened_concurrently)
        self.opened_concurrently = None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del self._working

    def commit(self) -> None:
        self.committed = copy.deepcopy(self._working)

    def add_event(self, event: DomainEvent) -> None:
        self._working.events.append(event)
