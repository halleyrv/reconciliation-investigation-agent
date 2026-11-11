"""``/reconciliation-runs`` and ``/discrepancies``: run the engine for a period, inspect output."""

import base64
import binascii
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from recon.reconciliation.application.ports import DiscrepancyFilter, DiscrepancyView
from recon.reconciliation.application.reconcile_period import (
    MissingReferenceData,
    PeriodNotClosed,
    PeriodOverlaps,
    ReconcilePeriod,
    RunFailed,
    RunInProgress,
)
from recon.reconciliation.application.run_queries import (
    GetRunSummary,
    ListDiscrepancies,
    RunNotFound,
)
from recon.reconciliation.domain.results import DiscrepancyType, Period
from recon.reconciliation.domain.run import ReconciliationRun


class PeriodBody(BaseModel):
    """An inclusive period, like ``recon-reconcile --from/--to``."""

    model_config = ConfigDict(populate_by_name=True)

    start: date = Field(alias="from")
    end: date = Field(alias="to")


class Run(BaseModel):
    id: uuid.UUID
    period: PeriodBody
    ruleset_version: str
    status: str
    started_at: datetime
    finished_at: datetime | None


class Summary(BaseModel):
    match_groups: int
    discrepancies: dict[str, int]  # count per discrepancy type


class RunWithSummary(Run):
    summary: Summary


class Discrepancy(BaseModel):
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


class DiscrepancyPage(BaseModel):
    items: list[Discrepancy]
    next_cursor: str | None


def _run(run: ReconciliationRun) -> Run:
    return Run(
        id=run.id,
        period=PeriodBody.model_validate({"from": run.period.start, "to": run.period.end}),
        ruleset_version=run.ruleset_version,
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _discrepancy(view: DiscrepancyView) -> Discrepancy:
    return Discrepancy(
        id=view.id,
        run_id=view.run_id,
        type=view.type,
        severity=view.severity,
        expected_minor=view.expected_minor,
        actual_minor=view.actual_minor,
        delta_minor=view.delta_minor,
        currency=view.currency,
        status=view.status,
        detected_at=view.detected_at,
    )


def _encode_cursor(after: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(after.bytes).rstrip(b"=").decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        return uuid.UUID(bytes=raw)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "malformed cursor: pass a next_cursor unchanged") from exc


def runs_router(
    reconcile: Callable[[], ReconcilePeriod],
    get_summary: Callable[[], GetRunSummary],
    list_discrepancies: Callable[[], ListDiscrepancies],
    after_write: Callable[[], None],
) -> APIRouter:
    router = APIRouter(tags=["reconciliation"])

    @router.post("/reconciliation-runs")
    def post_run(body: PeriodBody) -> Run:
        """Idempotent by (period, ruleset version): the ruleset in force, not a client choice."""
        try:
            period = Period(body.start, body.end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            run = reconcile()(period)
        except (PeriodOverlaps, RunInProgress, PeriodNotClosed) as exc:
            raise HTTPException(409, str(exc)) from exc
        except RunFailed as exc:  # recorded as failed with no output; a new POST may retry
            # only domain causes are worded for clients; any other text may carry internals
            detail = (
                str(exc.__cause__)
                if isinstance(exc.__cause__, MissingReferenceData)
                else "the run failed and was recorded as failed; a new request may retry"
            )
            raise HTTPException(422, {"detail": detail, "run_id": str(exc.run.id)}) from exc
        after_write()
        return _run(run)

    @router.get("/reconciliation-runs/{id}")
    def get_run(id: uuid.UUID) -> RunWithSummary:
        try:
            summary = get_summary()(id)
        except RunNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return RunWithSummary(
            **_run(summary.run).model_dump(),
            summary=Summary(
                match_groups=summary.match_groups,
                discrepancies=dict(summary.discrepancies_by_type),
            ),
        )

    @router.get("/discrepancies")
    def get_discrepancies(
        run_id: uuid.UUID | None = None,
        type: DiscrepancyType | None = None,
        severity: Literal["low", "medium", "high"] | None = None,
        min_abs_delta: Annotated[int | None, Query(ge=0, description="minor units")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: str | None = None,
    ) -> DiscrepancyPage:
        """Ordered by ID. Follow ``next_cursor`` until it is null to walk every match."""
        after = None if cursor is None else _decode_cursor(cursor)
        page = list_discrepancies()(
            DiscrepancyFilter(run_id, type, severity, min_abs_delta), after, limit
        )
        return DiscrepancyPage(
            items=[_discrepancy(v) for v in page.items],
            next_cursor=None if page.next_after is None else _encode_cursor(page.next_after),
        )

    return router
