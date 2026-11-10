"""Business-day calendar (ADR-0014): Monday to Friday minus a configured holiday list."""

from collections.abc import Collection
from datetime import date, timedelta


def is_business_day(day: date, holidays: Collection[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def add_business_days(day: date, days: int, holidays: Collection[date]) -> date:
    current = day
    added = 0
    while added < days:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            added += 1
    return current
