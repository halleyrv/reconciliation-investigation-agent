"""Import one simulator export: every file is checked against the manifest, then each file is
its own batch in its own transaction (assumption A3 of odd/tasks/p2a-ingestion.md)."""

from collections.abc import Mapping
from dataclasses import dataclass

from recon.ingestion.application.ports import IngestionUnitOfWork
from recon.ingestion.domain.batch import ImportBatch, RowError
from recon.ingestion.domain.events import SourceConflictDetected
from recon.ingestion.domain.records import (
    SOURCE_OF,
    RawRecord,
    RecordType,
    SourceConflict,
    SourceRecord,
)
from recon.shared_kernel.ports import Clock, IdGenerator


@dataclass(frozen=True, slots=True)
class ParsedRow:
    line_no: int
    payload: dict[str, object]
    payload_sha256: str
    record: SourceRecord


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A file as read and validated by an adapter: either rows or the errors that reject it."""

    name: str
    sha256: str
    record_type: RecordType
    rows: tuple[ParsedRow, ...]
    errors: tuple[RowError, ...]


@dataclass(frozen=True, slots=True)
class SimulatorExport:
    manifest: Mapping[str, str]
    files: tuple[SourceFile, ...]


class ManifestMismatch(Exception):
    def __init__(self, file_names: list[str]) -> None:
        super().__init__(f"SHA-256 differs from manifest.json for: {', '.join(file_names)}")
        self.file_names = file_names


class ImportExport:
    def __init__(self, uow: IngestionUnitOfWork, clock: Clock, ids: IdGenerator) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    def __call__(self, export: SimulatorExport) -> list[ImportBatch]:
        mismatched = [f.name for f in export.files if export.manifest.get(f.name) != f.sha256]
        if mismatched:
            raise ManifestMismatch(mismatched)
        return [self._import(f) for f in export.files]

    def _import(self, file: SourceFile) -> ImportBatch:
        source = SOURCE_OF[file.record_type]
        with self._uow:
            # Without the lock, two concurrent imports both see no batch and one fails on the
            # unique key instead of returning the batch the other wrote.
            self._uow.batches.lock_source(source)
            existing = self._uow.batches.get_by_file(source, file.sha256)
            if existing is not None:
                return existing
            now = self._clock.now()
            batch = ImportBatch.start(
                self._ids.new(), source, file.record_type, file.name, file.sha256, now
            )
            self._uow.batches.add(batch)
            if file.errors:
                batch.fail(file.errors, now)
            else:
                ids = {row.record.external_id for row in file.rows}
                canonical = self._uow.records.find_canonical_raws(source, file.record_type, ids)
                conflicts = self._uow.records.find_conflict_payloads(source, file.record_type, ids)
                raws = [self._raw(batch, row) for row in file.rows]
                for raw in raws:
                    self._uow.records.add_raw(raw)
                for row, raw in zip(file.rows, raws, strict=True):
                    self._store(batch, row, raw, canonical, conflicts)
                batch.complete(len(file.rows), now)
            self._uow.batches.save(batch)
            self._uow.commit()
            return batch

    def _raw(self, batch: ImportBatch, row: ParsedRow) -> RawRecord:
        return RawRecord(
            self._ids.new(), batch.id, batch.source, row.line_no, row.payload, row.payload_sha256
        )

    def _store(
        self,
        batch: ImportBatch,
        row: ParsedRow,
        raw: RawRecord,
        canonical: dict[str, RawRecord],
        conflicts: set[tuple[str, str]],
    ) -> None:
        """First seen wins: ``canonical`` maps each external ID to the raw record it came from.
        ``conflicts`` holds the ``(external_id, payload SHA-256)`` pairs already recorded."""
        external_id = row.record.external_id
        existing = canonical.get(external_id)
        if existing is None:
            self._uow.records.add(row.record, raw)
            canonical[external_id] = raw
        elif (
            existing.payload_sha256 != raw.payload_sha256
            and (external_id, raw.payload_sha256) not in conflicts
        ):
            conflicts.add((external_id, raw.payload_sha256))
            conflict = SourceConflict(
                self._ids.new(),
                batch.source,
                batch.record_type,
                external_id,
                existing.id,
                raw.id,
                raw.payload_sha256,
                self._clock.now(),
            )
            self._uow.records.add_conflict(conflict)
            self._uow.add_event(
                SourceConflictDetected(
                    occurred_at=conflict.detected_at,
                    conflict_id=conflict.id,
                    source=conflict.source,
                    record_type=conflict.record_type,
                    external_id=external_id,
                    existing_raw_record_id=existing.id,
                    incoming_raw_record_id=raw.id,
                )
            )
