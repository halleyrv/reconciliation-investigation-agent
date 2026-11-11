"""ReconciliationCase: the unit of work an investigator (later the agent) takes on, one per
discrepancy. Every change is guarded by an optimistic version check."""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CaseStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ReconciliationCase:
    id: uuid.UUID
    discrepancy_id: uuid.UUID
    status: CaseStatus
    priority: Priority
    opened_at: datetime
    version: int
    assignee_id: str | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("a case version starts at 1")
        closed = self.status in (CaseStatus.RESOLVED, CaseStatus.ESCALATED)
        if closed != (self.closed_at is not None):
            raise ValueError("a case has a close time exactly when it is resolved or escalated")
        if self.assignee_id is not None and not self.assignee_id.strip():
            raise ValueError("an assignee needs a non-empty ID")

    @classmethod
    def open(
        cls, case_id: uuid.UUID, discrepancy_id: uuid.UUID, priority: Priority, at: datetime
    ) -> ReconciliationCase:
        return cls(case_id, discrepancy_id, CaseStatus.OPEN, priority, at, version=1)

    def reassigned(self, priority: Priority, assignee_id: str | None) -> ReconciliationCase:
        """The case with a new priority and assignee, one version later."""
        return dataclasses.replace(
            self, priority=priority, assignee_id=assignee_id, version=self.version + 1
        )
