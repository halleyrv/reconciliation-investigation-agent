"""Business-day calendar (ADR-0014): Monday to Friday minus the operator-loaded holidays."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class BusinessCalendar:
    holidays: frozenset[date]

    def is_business_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def add_business_days(self, day: date, days: int) -> date:
        current, added = day, 0
        while added < days:
            current += timedelta(days=1)
            if self.is_business_day(current):
                added += 1
        return current
