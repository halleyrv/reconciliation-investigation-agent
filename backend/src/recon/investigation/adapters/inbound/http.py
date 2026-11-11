"""``/cases``: open a discrepancy's case, list and inspect cases, change priority or assignee
under an optimistic version (D1), read a case's audit history."""

import base64
import binascii
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from recon.investigation.application.case_queries import GetCaseDetail, GetCaseHistory, ListCases
from recon.investigation.application.open_case import DiscrepancyNotFound, OpenCase
from recon.investigation.application.ports import CaseFilter, DiscrepancySnapshot
from recon.investigation.application.update_case import (
    UNCHANGED,
    CaseNotFound,
    StaleVersion,
    UpdateCase,
)
from recon.investigation.domain.case import CaseStatus, Priority, ReconciliationCase
from recon.reconciliation.api import DiscrepancyType
from recon.shared_kernel.actor import Actor, ActorType


class OpenCaseBody(BaseModel):
    discrepancy_id: uuid.UUID


class UpdateCaseBody(BaseModel):
    """Only the fields present change; ``assignee_id: null`` unassigns. Status transitions
    belong to later phases (D1), so any other field is refused."""

    model_config = ConfigDict(extra="forbid")

    priority: Priority | None = None
    assignee_id: Annotated[str | None, Field(min_length=1)] = None


class Case(BaseModel):
    id: uuid.UUID
    discrepancy_id: uuid.UUID
    status: str
    priority: str
    assignee_id: str | None
    opened_at: datetime
    closed_at: datetime | None
    version: int


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


class Record(BaseModel):
    type: str
    id: uuid.UUID


class CaseDetail(Case):
    discrepancy: Discrepancy
    records: list[Record]


class CasePage(BaseModel):
    items: list[Case]
    next_cursor: str | None


class ActorBody(BaseModel):
    type: str
    id: str


class HistoryItem(BaseModel):
    event_type: str
    event_version: int
    occurred_at: datetime
    actor: ActorBody
    payload: dict[str, object]


class History(BaseModel):
    items: list[HistoryItem]


def _case(case: ReconciliationCase) -> Case:
    return Case(
        id=case.id,
        discrepancy_id=case.discrepancy_id,
        status=case.status.value,
        priority=case.priority.value,
        assignee_id=case.assignee_id,
        opened_at=case.opened_at,
        closed_at=case.closed_at,
        version=case.version,
    )


def _discrepancy(view: DiscrepancySnapshot) -> Discrepancy:
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


def _etag(response: Response, case: ReconciliationCase) -> None:
    response.headers["ETag"] = f'"{case.version}"'


_VERSION_TAG = re.compile(r'"?([0-9]+)"?')


def _expected_version(if_match: str | None) -> int:
    """One strong entity tag, ``"<version>"`` as the ETag gives it (or the bare number)."""
    tag = None if if_match is None else if_match.strip()
    if tag is None or tag == "*":
        raise HTTPException(428, "send If-Match with the case version (its ETag) you read")
    if tag.startswith("W/"):
        # RFC 9110 13.1.1: If-Match uses the strong comparison, a weak tag never matches
        raise HTTPException(412, "a weak entity tag never matches If-Match; send the ETag as is")
    match = _VERSION_TAG.fullmatch(tag)
    if match is None or tag.count('"') == 1:
        raise HTTPException(422, "If-Match must be one case version, as in its ETag")
    return int(match.group(1))


# shortcut: the same cursor codec as the discrepancies router; contexts share no adapter code
def _encode_cursor(after: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(after.bytes).rstrip(b"=").decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        return uuid.UUID(bytes=raw)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "malformed cursor: pass a next_cursor unchanged") from exc


def cases_router(
    open_case: Callable[[], OpenCase],
    get_detail: Callable[[], GetCaseDetail],
    list_cases: Callable[[], ListCases],
    get_history: Callable[[], GetCaseHistory],
    update_case: Callable[[Actor], UpdateCase],
    after_write: Callable[[], None],
) -> APIRouter:
    router = APIRouter(tags=["cases"])

    @router.post("/cases", status_code=200, responses={201: {"model": Case}})
    def post_case(body: OpenCaseBody, response: Response) -> Case:
        """Idempotent: one case per discrepancy. ``201`` when opened, ``200`` when it existed."""
        try:
            opened = open_case()(body.discrepancy_id)
        except DiscrepancyNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        if opened.created:
            response.status_code = 201
            after_write()
        _etag(response, opened.case)
        return _case(opened.case)

    @router.get("/cases")
    def get_cases(
        status: CaseStatus | None = None,
        discrepancy_type: DiscrepancyType | None = None,
        run_id: uuid.UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: str | None = None,
    ) -> CasePage:
        """Ordered by ID. Follow ``next_cursor`` until it is null to walk every match."""
        after = None if cursor is None else _decode_cursor(cursor)
        where = CaseFilter(
            status, None if discrepancy_type is None else discrepancy_type.value, run_id
        )
        page = list_cases()(where, after, limit)
        return CasePage(
            items=[_case(c) for c in page.items],
            next_cursor=None if page.next_after is None else _encode_cursor(page.next_after),
        )

    @router.get("/cases/{id}")
    def get_case(id: uuid.UUID, response: Response) -> CaseDetail:
        try:
            detail = get_detail()(id)
        except CaseNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        _etag(response, detail.case)
        return CaseDetail(
            **_case(detail.case).model_dump(),
            discrepancy=_discrepancy(detail.discrepancy),
            records=[Record(type=r.type, id=r.id) for r in detail.records],
        )

    @router.patch("/cases/{id}")
    def patch_case(
        id: uuid.UUID,
        body: UpdateCaseBody,
        response: Response,
        x_actor_id: Annotated[str, Header(min_length=1, description="claimed, unverified")],
        if_match: Annotated[str | None, Header()] = None,
    ) -> Case:
        """Changes ``priority`` and ``assignee_id``. ``If-Match`` names the version read; a
        stale one is ``409`` and changes nothing."""
        expected = _expected_version(if_match)
        fields = body.model_fields_set
        if "priority" in fields and body.priority is None:
            raise HTTPException(422, "priority cannot be null")
        try:
            actor = Actor(ActorType.USER, x_actor_id)  # ADR-0018: no authentication yet
            case = update_case(actor)(
                id,
                expected_version=expected,
                priority=body.priority if body.priority is not None else UNCHANGED,
                assignee_id=body.assignee_id if "assignee_id" in fields else UNCHANGED,
            )
        except CaseNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except StaleVersion as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        after_write()
        _etag(response, case)
        return _case(case)

    @router.get("/cases/{id}/history")
    def get_case_history(id: uuid.UUID) -> History:
        """The case's events from the audit trail, oldest first, each with its actor."""
        try:
            entries = get_history()(id)
        except CaseNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return History(
            items=[
                HistoryItem(
                    event_type=e.event_type,
                    event_version=e.event_version,
                    occurred_at=e.occurred_at,
                    actor=ActorBody(type=e.actor.type.value, id=e.actor.id),
                    payload=e.payload,
                )
                for e in entries
            ]
        )

    return router
