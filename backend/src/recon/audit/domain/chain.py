"""The audit hash chain: each entry's SHA-256 covers its content and its predecessor's hash,
so changing, removing or reordering any entry breaks every hash after it."""

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from recon.shared_kernel.actor import Actor


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One domain event as audited: where it came from, who caused it, and what it says."""

    source: str
    source_event_id: int
    occurred_at: datetime
    actor: Actor
    aggregate_type: str | None
    aggregate_id: uuid.UUID | None
    event_type: str
    event_version: int
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ChainedEntry:
    id: int
    record: AuditRecord
    prev_sha256: str | None
    sha256: str


def entry_hash(record: AuditRecord, prev_sha256: str | None) -> str:
    content = {
        "source": record.source,
        "source_event_id": record.source_event_id,
        "occurred_at": record.occurred_at.astimezone(UTC).isoformat(),
        "actor_type": record.actor.type.value,
        "actor_id": record.actor.id,
        "aggregate_type": record.aggregate_type,
        "aggregate_id": None if record.aggregate_id is None else str(record.aggregate_id),
        "event_type": record.event_type,
        "event_version": record.event_version,
        "payload": record.payload,
        "prev_sha256": prev_sha256,
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def first_broken(entries: Iterable[ChainedEntry]) -> int | None:
    """The ID of the first entry, in chain order, whose link or content does not verify."""
    prev: str | None = None
    for entry in entries:
        if entry.prev_sha256 != prev or entry_hash(entry.record, prev) != entry.sha256:
            return entry.id
        prev = entry.sha256
    return None
