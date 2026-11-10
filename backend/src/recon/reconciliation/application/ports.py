import uuid
from datetime import date, datetime
from typing import Protocol

from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.results import Discrepancy, MatchGroup, Period
from recon.reconciliation.domain.run import ReconciliationRun
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.ports import UnitOfWork


class RunRepository(Protocol):
    def lock(self, period: Period, ruleset_version: str) -> None:
        """Serialize runs of one period and ruleset until the current transaction ends."""
        ...

    def find_live(self, period: Period, ruleset_version: str) -> ReconciliationRun | None:
        """The running or completed run of this period and ruleset, if any."""
        ...

    def add(self, run: ReconciliationRun) -> None: ...

    def save(self, run: ReconciliationRun) -> None: ...


class SourceRecordReader(Protocol):
    def snapshot(self, currency: str) -> Snapshot:
        """Every canonical source record Ingestion holds, read-only."""
        ...


class ReferenceDataRepository(Protocol):
    def fee_schedules(self) -> tuple[FeeSchedule, ...]: ...

    def holidays(self) -> frozenset[date]: ...

    def add_fee_schedule(self, schedule_id: uuid.UUID, schedule: FeeSchedule) -> None: ...

    def add_holiday(self, day: date) -> None: ...


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


class ReconciliationUnitOfWork(UnitOfWork, Protocol):
    @property
    def runs(self) -> RunRepository: ...

    @property
    def sources(self) -> SourceRecordReader: ...

    @property
    def reference(self) -> ReferenceDataRepository: ...

    @property
    def results(self) -> ResultRepository: ...
