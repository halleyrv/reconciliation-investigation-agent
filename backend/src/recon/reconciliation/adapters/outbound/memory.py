"""In-memory unit of work for application tests. It keeps the rules the use case relies on:
one live run per period and ruleset, unique fingerprints, a record in one group per run."""

import copy
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from types import TracebackType
from typing import Self

from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.records import RecordRef
from recon.reconciliation.domain.results import Discrepancy, MatchGroup, Period
from recon.reconciliation.domain.run import ReconciliationRun, RunStatus
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.events import DomainEvent


class UniqueViolation(Exception):
    pass


@dataclass
class State:
    runs: dict[uuid.UUID, ReconciliationRun] = field(default_factory=dict)
    groups: dict[uuid.UUID, tuple[uuid.UUID, MatchGroup]] = field(default_factory=dict)
    discrepancies: dict[uuid.UUID, tuple[uuid.UUID, Discrepancy, str]] = field(default_factory=dict)
    events: list[DomainEvent] = field(default_factory=list)
    fee_schedules: dict[uuid.UUID, FeeSchedule] = field(default_factory=dict)
    holidays: frozenset[date] = frozenset()


class _Runs:
    def __init__(self, state: State) -> None:
        self._state = state

    def lock(self, period: Period, ruleset_version: str) -> None:
        pass  # one thread: nothing to serialize

    def find_live(self, period: Period, ruleset_version: str) -> ReconciliationRun | None:
        return next(
            (
                r
                for r in self._state.runs.values()
                if (r.period, r.ruleset_version) == (period, ruleset_version)
                and r.status is not RunStatus.FAILED
            ),
            None,
        )

    def add(self, run: ReconciliationRun) -> None:
        if run.status is not RunStatus.FAILED and self.find_live(run.period, run.ruleset_version):
            raise UniqueViolation("a live run of this period and ruleset exists")
        self._state.runs[run.id] = run

    def save(self, run: ReconciliationRun) -> None:
        self._state.runs[run.id] = run


class _Sources:
    def __init__(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self, currency: str) -> Snapshot:
        return self._snapshot


class _Reference:
    def __init__(self, state: State) -> None:
        self._state = state

    def fee_schedules(self) -> tuple[FeeSchedule, ...]:
        return tuple(self._state.fee_schedules.values())

    def holidays(self) -> frozenset[date]:
        return self._state.holidays

    def add_fee_schedule(self, schedule_id: uuid.UUID, schedule: FeeSchedule) -> None:
        if any(schedule.overlaps(s) for s in self._state.fee_schedules.values()):
            raise UniqueViolation("overlapping fee schedule")  # the EXCLUDE constraint
        self._state.fee_schedules[schedule_id] = schedule

    def add_holiday(self, day: date) -> None:
        if day in self._state.holidays:
            raise UniqueViolation(f"holiday {day} exists")
        self._state.holidays |= {day}


class _Results:
    def __init__(self, state: State, fail_on_discrepancy: int | None) -> None:
        self._state = state
        self._fail_on = fail_on_discrepancy
        self._written = 0

    def add_group(self, run_id: uuid.UUID, group_id: uuid.UUID, group: MatchGroup) -> None:
        grouped: set[RecordRef] = {
            m.ref for r, g in self._state.groups.values() if r == run_id for m in g.members
        }
        if grouped & {m.ref for m in group.members}:
            raise UniqueViolation("a record belongs to one match group per run")
        self._state.groups[group_id] = (run_id, group)

    def add_discrepancy(
        self,
        run_id: uuid.UUID,
        discrepancy_id: uuid.UUID,
        discrepancy: Discrepancy,
        period: Period,
        detected_at: datetime,
    ) -> None:
        self._written += 1
        if self._written == self._fail_on:
            raise RuntimeError("injected failure while writing discrepancies")
        fingerprint = discrepancy.fingerprint(period)
        if any(f == fingerprint for _, _, f in self._state.discrepancies.values()):
            raise UniqueViolation(f"fingerprint {fingerprint} exists")
        self._state.discrepancies[discrepancy_id] = (run_id, discrepancy, fingerprint)


class InMemoryReconciliationUnitOfWork:
    """``committed`` is what a later transaction sees; a block without ``commit`` leaves it."""

    runs: _Runs
    sources: _Sources
    reference: _Reference
    results: _Results

    def __init__(
        self,
        snapshot: Snapshot,
        fee_schedules: tuple[FeeSchedule, ...] = (),
        holidays: frozenset[date] = frozenset(),
        fail_on_discrepancy: int | None = None,
    ) -> None:
        self.committed = State(
            fee_schedules={uuid.UUID(int=n): s for n, s in enumerate(fee_schedules, 1)},
            holidays=holidays,
        )
        self.sources = _Sources(snapshot)
        self.fail_on_discrepancy = fail_on_discrepancy  # test hook, read by each transaction

    def __enter__(self) -> Self:
        self._working = copy.deepcopy(self.committed)
        self.runs = _Runs(self._working)
        self.results = _Results(self._working, self.fail_on_discrepancy)
        self.reference = _Reference(self._working)
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
