"""Queries the API asks about cases."""

import uuid
from dataclasses import dataclass

from recon.investigation.application.ports import (
    CaseDetail,
    CaseFilter,
    CaseQueries,
    HistoryEntry,
)
from recon.investigation.application.update_case import CaseNotFound
from recon.investigation.domain.case import ReconciliationCase


class GetCaseDetail:
    def __init__(self, queries: CaseQueries) -> None:
        self._queries = queries

    def __call__(self, case_id: uuid.UUID) -> CaseDetail:
        detail = self._queries.detail(case_id)
        if detail is None:
            raise CaseNotFound(case_id)
        return detail


class GetCaseHistory:
    def __init__(self, queries: CaseQueries) -> None:
        self._queries = queries

    def __call__(self, case_id: uuid.UUID) -> list[HistoryEntry]:
        history = self._queries.history(case_id)
        if history is None:
            raise CaseNotFound(case_id)
        return history


@dataclass(frozen=True, slots=True)
class CasePage:
    items: list[ReconciliationCase]
    next_after: uuid.UUID | None  # the keyset of the next page; None on the last one


class ListCases:
    """Keyset pagination by ID, like ``ListDiscrepancies``: each case present for the whole
    walk is returned exactly once."""

    def __init__(self, queries: CaseQueries) -> None:
        self._queries = queries

    def __call__(self, where: CaseFilter, after: uuid.UUID | None, limit: int) -> CasePage:
        rows = self._queries.cases(where, after, limit + 1)
        items = rows[:limit]
        return CasePage(items, items[-1].id if len(rows) > limit else None)
