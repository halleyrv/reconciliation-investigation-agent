import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from recon.audit.adapters.outbound.memory import InMemoryAuditUnitOfWork
from recon.audit.application.record_event import RecordEvent, VerifyChain
from recon.audit.domain.chain import AuditRecord, first_broken
from recon.shared_kernel.actor import Actor, ActorType

AT = datetime(2026, 11, 10, 12, tzinfo=UTC)


def _record(n: int) -> AuditRecord:
    return AuditRecord(
        source="recon.outbox",
        source_event_id=n,
        occurred_at=AT,
        actor=Actor.system("recon-reconcile"),
        aggregate_type="Discrepancy",
        aggregate_id=uuid.UUID(int=n),
        event_type="DiscrepancyDetected",
        event_version=1,
        payload={"discrepancy_id": str(uuid.UUID(int=n)), "delta_minor": n},
    )


def test_recorded_events_form_a_chain_that_verifies() -> None:
    uow = InMemoryAuditUnitOfWork()

    assert RecordEvent(uow)(_record(1)) and RecordEvent(uow)(_record(2))

    first, second = uow.entries
    assert (first.id, first.prev_sha256, second.prev_sha256) == (1, None, first.sha256)
    assert first.record == _record(1) and len(first.sha256) == 64
    report = VerifyChain(uow)()
    assert (report.entries, report.first_broken) == (2, None)


def test_a_redelivered_event_is_recorded_once() -> None:
    uow = InMemoryAuditUnitOfWork()
    RecordEvent(uow)(_record(1))

    assert not RecordEvent(uow)(_record(1))

    assert len(uow.entries) == 1


def test_verification_names_the_first_entry_whose_content_or_link_changed() -> None:
    uow = InMemoryAuditUnitOfWork()
    for n in (1, 2, 3):
        RecordEvent(uow)(_record(n))
    entries = list(uow.entries)

    tampered = replace(entries[1], record=replace(entries[1].record, payload={"delta_minor": 0}))
    relinked = replace(entries[2], prev_sha256=entries[0].sha256)

    assert first_broken([entries[0], tampered, entries[2]]) == 2
    assert first_broken([entries[0], entries[1], relinked]) == 3
    assert first_broken(entries) is None


@pytest.mark.parametrize("actor_id", ["", " "])
def test_an_actor_needs_an_id(actor_id: str) -> None:
    with pytest.raises(ValueError):
        Actor(ActorType.USER, actor_id)
