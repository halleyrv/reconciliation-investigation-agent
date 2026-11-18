"""Queries the API asks about runs and discrepancies."""

import uuid
from dataclasses import dataclass

from recon.reconciliation.application.ports import (
    DiscrepancyFilter,
    DiscrepancyView,
    RunQueries,
    RunSummary,
)


class RunNotFound(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"no reconciliation run {run_id}")


class GetRunSummary:
    def __init__(self, queries: RunQueries) -> None:
        self._queries = queries

    def __call__(self, run_id: uuid.UUID) -> RunSummary:
        summary = self._queries.summary(run_id)
        if summary is None:
            raise RunNotFound(run_id)
        return summary


@dataclass(frozen=True, slots=True)
class DiscrepancyPage:
    items: list[DiscrepancyView]
    next_after: uuid.UUID | None  # the keyset of the next page; None on the last one


class ListDiscrepancies:
    """Keyset pagination by ID: a row inserted between pages never shifts the walk, so each
    row present for the whole walk is returned exactly once."""

    def __init__(self, queries: RunQueries) -> None:
        self._queries = queries

    def __call__(
        self, where: DiscrepancyFilter, after: uuid.UUID | None, limit: int
    ) -> DiscrepancyPage:
        rows = self._queries.discrepancies(where, after, limit + 1)
        items = rows[:limit]
        return DiscrepancyPage(items, items[-1].id if len(rows) > limit else None)
