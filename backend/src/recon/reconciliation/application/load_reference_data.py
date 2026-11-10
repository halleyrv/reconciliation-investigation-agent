"""Use case: an operator loads fee schedules and bank holidays (OD1, AS3). Idempotent."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from recon.reconciliation.application.ports import ReconciliationUnitOfWork
from recon.reconciliation.domain.fees import FeeSchedule
from recon.shared_kernel.ports import IdGenerator


class ReferenceDataConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LoadResult:
    schedules_added: int
    holidays_added: int


class LoadReferenceData:
    def __init__(self, uow: ReconciliationUnitOfWork, ids: IdGenerator) -> None:
        self._uow = uow
        self._ids = ids

    def __call__(self, schedules: Iterable[FeeSchedule], holidays: Iterable[date]) -> LoadResult:
        """Add what is not loaded yet, in one transaction. A schedule that overlaps a different
        one already loaded (or another in the input) changes nothing and raises."""
        with self._uow as uow:
            loaded = list(uow.reference.fee_schedules())
            new: list[FeeSchedule] = []
            for schedule in dict.fromkeys(schedules):  # keeps order, drops repeats
                if schedule in loaded:
                    continue
                clash = next((s for s in (*loaded, *new) if schedule.overlaps(s)), None)
                if clash is not None:
                    raise ReferenceDataConflict(
                        f"{schedule.gateway} {schedule.fee_type} from {schedule.valid_from}"
                        f" overlaps the schedule from {clash.valid_from}"
                    )
                new.append(schedule)
            known = uow.reference.holidays()
            days = sorted(set(holidays) - known)
            for schedule in new:
                uow.reference.add_fee_schedule(self._ids.new(), schedule)
            for day in days:
                uow.reference.add_holiday(day)
            uow.commit()
        return LoadResult(len(new), len(days))
