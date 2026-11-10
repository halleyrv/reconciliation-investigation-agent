from collections.abc import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from recon.bootstrap.settings import database_url
from recon.ingestion.adapters.inbound import cli
from recon.ingestion.adapters.outbound.sql import SqlAlchemyIngestionUnitOfWork
from recon.ingestion.application.import_export import ImportExport
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
