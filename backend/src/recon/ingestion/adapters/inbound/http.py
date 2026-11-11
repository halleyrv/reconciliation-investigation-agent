"""``POST /imports`` and ``GET /imports/{id}``: import a simulator export and inspect a batch."""

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from recon.ingestion.adapters.outbound.simulator_files import ExportUnreadable, read_export
from recon.ingestion.application.get_import_batch import GetImportBatch, ImportBatchNotFound
from recon.ingestion.application.import_export import ImportExport, ManifestMismatch
from recon.ingestion.domain.batch import ImportBatch


class ImportRequest(BaseModel):
    directory: str


class BatchError(BaseModel):
    file: str
    line: int
    field: str
    message: str


class Batch(BaseModel):
    id: uuid.UUID
    source: str
    file_name: str
    record_type: str
    status: str
    row_count: int
    errors: list[BatchError]
    started_at: datetime
    finished_at: datetime | None


def _batch(batch: ImportBatch) -> Batch:
    return Batch(
        id=batch.id,
        source=batch.source,
        file_name=batch.file_name,
        record_type=batch.record_type.value,
        status=batch.status,
        row_count=batch.row_count,
        errors=[
            BatchError(file=e.file_name, line=e.line_no, field=e.field, message=e.message)
            for e in batch.errors
        ],
        started_at=batch.started_at,
        finished_at=batch.finished_at,
    )


def _inside(root: Path | None, directory: str) -> Path:
    """The trust boundary: the client names a path, the server reads only under its root."""
    if root is None:
        raise HTTPException(422, "imports are disabled: RECON_IMPORT_ROOT is not set")
    path = Path(directory).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(422, "the directory is outside RECON_IMPORT_ROOT")
    return path


def imports_router(
    import_export: Callable[[], ImportExport],
    get_batch: Callable[[], GetImportBatch],
    import_root: Path | None,
    after_write: Callable[[], None],
) -> APIRouter:
    router = APIRouter(tags=["imports"])

    @router.post("/imports")
    def post_import(request: ImportRequest) -> list[Batch]:
        directory = _inside(import_root, request.directory)
        try:
            batches = import_export()(read_export(directory))
        except (ManifestMismatch, ExportUnreadable) as exc:
            raise HTTPException(422, f"nothing imported: {exc}") from exc
        except OSError as exc:  # its message names server paths: keep it out of the response
            raise HTTPException(422, "nothing imported: not a simulator export directory") from exc
        after_write()
        return [_batch(b) for b in batches]

    @router.get("/imports/{id}")
    def get_import(id: uuid.UUID) -> Batch:
        try:
            return _batch(get_batch()(id))
        except ImportBatchNotFound as exc:
            raise HTTPException(404, str(exc)) from exc

    return router
