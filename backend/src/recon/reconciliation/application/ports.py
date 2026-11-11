import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from recon.reconciliation.application.evaluation import Finding, Link
from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.results import Discrepancy, DiscrepancyType, MatchGroup, Period
from recon.reconciliation.domain.run import ReconciliationRun
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.ports import UnitOfWork


class RunRepository(Protocol):
    def lock(self, period: Period, ruleset_version: str) -> None:
        """Serialize run starts of one ruleset until the current transaction ends."""
        ...

    def find_live(self, period: Period, ruleset_version: str) -> ReconciliationRun | None:
        """The running or completed run of this period and ruleset, if any."""
        ...

    def find_overlapping(self, period: Period, ruleset_version: str) -> ReconciliationRun | None:
        """A live run of this ruleset whose different period shares a day with ``period``."""
        ...

    def add(self, run: ReconciliationRun) -> None: ...

    def save(self, run: ReconciliationRun) -> None: ...


class SourceRecordReader(Protocol):
    def snapshot(self, currency: str) -> Snapshot:
        """Every canonical source record Ingestion holds, read-only."""
        ...

    def latest_bank_date(self) -> date | None:
        """The latest value date of any imported bank transaction: how far bank data reaches."""
        ...


class ReferenceDataRepository(Protocol):
    def fee_schedules(self) -> tuple[FeeSchedule, ...]: ...

    def holidays(self) -> frozenset[date]: ...

    def add_fee_schedule(self, schedule_id: uuid.UUID, schedule: FeeSchedule) -> None: ...

    def add_holiday(self, day: date) -> None: ...

    def calendar_years(self) -> frozenset[int]:
        """Years whose holiday list was loaded, so a year with no holidays is still known."""
        ...

    def add_calendar_year(self, year: int) -> None: ...


class ResultRepository(Protocol):
    """Writes a run's output. Records are named by ``RecordRef`` from the last snapshot read."""

    def add_group(self, run_id: uuid.UUID, group_id: uuid.UUID, group: MatchGroup) -> None: ...

    def add_discrepancy(
        self,
        run_id: uuid.UUID,
        discrepancy_id: uuid.UUID,
        discrepancy: Discrepancy,
        period: Period,
        detected_at: datetime,
    ) -> None: ...


class RunOutputReader(Protocol):
    """A completed run's output, named by external IDs, for evaluation and reports."""

    def findings(self, run_id: uuid.UUID) -> list[Finding]: ...

    def links(self, run_id: uuid.UUID) -> set[Link]:
        """Order -> payment -> settlement -> payout, for every order in a match group."""
        ...


class ReconciliationUnitOfWork(UnitOfWork, Protocol):
    @property
    def runs(self) -> RunRepository: ...

    @property
    def sources(self) -> SourceRecordReader: ...

    @property
    def reference(self) -> ReferenceDataRepository: ...

    @property
    def results(self) -> ResultRepository: ...

    @property
    def outputs(self) -> RunOutputReader: ...


@dataclass(frozen=True, slots=True)
class RunSummary:
    run: ReconciliationRun
    match_groups: int
    discrepancies_by_type: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class DiscrepancyFilter:
    """Every field is optional; the ones given all apply."""

    run_id: uuid.UUID | None = None
    type: DiscrepancyType | None = None
    severity: str | None = None
    min_abs_delta_minor: int | None = None


@dataclass(frozen=True, slots=True)
class DiscrepancyView:
    id: uuid.UUID
    run_id: uuid.UUID
    type: str
    severity: str
    expected_minor: int
    actual_minor: int
    delta_minor: int
    currency: str
    status: str
    detected_at: datetime


class RunQueries(Protocol):
    """What the API reads about runs and their discrepancies: views, not aggregates."""

    def summary(self, run_id: uuid.UUID) -> RunSummary | None: ...

    def discrepancies(
        self, where: DiscrepancyFilter, after: uuid.UUID | None, limit: int
    ) -> list[DiscrepancyView]:
        """At most ``limit`` matching discrepancies whose ID is above ``after``, by ID."""
        ...
