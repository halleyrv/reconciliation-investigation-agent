from collections.abc import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from recon.bootstrap.settings import database_url
from recon.ingestion.adapters.inbound import cli
from recon.ingestion.adapters.outbound.sql import SqlAlchemyIngestionUnitOfWork
from recon.ingestion.application.import_export import ImportExport
from recon.reconciliation.adapters.inbound.cli import run_reference
from recon.reconciliation.adapters.outbound.sql import SqlAlchemyReconciliationUnitOfWork
from recon.reconciliation.application.load_reference_data import LoadReferenceData
from recon.shared_kernel.ports import SystemClock, UuidIdGenerator


def main(argv: Sequence[str] | None = None) -> int:
    engine = create_engine(database_url())
    try:
        return cli.run(
            argv,
            lambda: ImportExport(
                SqlAlchemyIngestionUnitOfWork(sessionmaker(engine)),
                SystemClock(),
                UuidIdGenerator(),
            ),
        )
    finally:
        engine.dispose()


def reference_main(argv: Sequence[str] | None = None) -> int:
    engine = create_engine(database_url())
    try:
        return run_reference(
            argv,
            lambda: LoadReferenceData(
                SqlAlchemyReconciliationUnitOfWork(sessionmaker(engine)), UuidIdGenerator()
            ),
        )
    finally:
        engine.dispose()
