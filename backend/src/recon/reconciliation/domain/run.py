"""ReconciliationRun: one execution of the engine for a period and ruleset. Moves forward only."""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from recon.reconciliation.domain.results import Period


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvalidRunTransition(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    id: uuid.UUID
    period: Period
    ruleset_version: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.ruleset_version:
            raise ValueError("ruleset_version must not be empty")
        if (self.status is RunStatus.RUNNING) != (self.finished_at is None):
            raise ValueError("a run has a finish time exactly when it is completed or failed")

    @classmethod
    def start(
        cls, run_id: uuid.UUID, period: Period, ruleset_version: str, at: datetime
    ) -> ReconciliationRun:
        return cls(run_id, period, ruleset_version, RunStatus.RUNNING, at)

    def completed(self, at: datetime) -> ReconciliationRun:
        return self._finish(RunStatus.COMPLETED, at)

    def failed(self, at: datetime) -> ReconciliationRun:
        return self._finish(RunStatus.FAILED, at)

    def _finish(self, status: RunStatus, at: datetime) -> ReconciliationRun:
        if self.status is not RunStatus.RUNNING:
            raise InvalidRunTransition(f"run {self.id} is {self.status}, cannot become {status}")
        return replace(self, status=status, finished_at=at)
