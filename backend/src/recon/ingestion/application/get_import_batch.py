"""Query: one import batch with its errors, as stored."""

import uuid

from recon.ingestion.application.ports import IngestionUnitOfWork
from recon.ingestion.domain.batch import ImportBatch


class ImportBatchNotFound(Exception):
    def __init__(self, batch_id: uuid.UUID) -> None:
        super().__init__(f"no import batch {batch_id}")


class GetImportBatch:
    def __init__(self, uow: IngestionUnitOfWork) -> None:
        self._uow = uow

    def __call__(self, batch_id: uuid.UUID) -> ImportBatch:
        with self._uow as uow:
            batch = uow.batches.get(batch_id)
        if batch is None:
            raise ImportBatchNotFound(batch_id)
        return batch
