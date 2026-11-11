import sys
from collections.abc import Callable, Sequence

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from recon.bootstrap.outbox import default_relay, dispatch
from recon.bootstrap.settings import database_url
from recon.ingestion.adapters.inbound import cli
from recon.ingestion.adapters.outbound.sql import SqlAlchemyIngestionUnitOfWork
from recon.ingestion.application.import_export import ImportExport
from recon.reconciliation.adapters.inbound.cli import run_evaluate, run_reconcile, run_reference
from recon.reconciliation.adapters.outbound.sql import SqlAlchemyReconciliationUnitOfWork
from recon.reconciliation.application.evaluate_run import EvaluateRun
from recon.reconciliation.application.load_reference_data import LoadReferenceData
from recon.reconciliation.application.reconcile_period import ReconcilePeriod
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.ports import SystemClock, UuidIdGenerator


def _dispatch(engine: Engine, command: str, exit_code: int) -> int:
    """Deliver the events a successful command wrote. Delivery problems are warnings: the
    events stay in their outbox for the next command, and the exit code is the command's."""
    if exit_code != 0:
        return exit_code
    for warning in dispatch(default_relay(engine)):
        print(f"{command}: warning: {warning}", file=sys.stderr)
    return exit_code


INFRASTRUCTURE_FAILURE = 3  # every command: the database is unreachable or not migrated


def _guarded(command: str, body: Callable[[], int]) -> int:
    """Run a command; a database failure is one stderr line and exit 3, never a traceback."""
    try:
        return body()
    except SQLAlchemyError as exc:
        reason = str(getattr(exc, "orig", None) or exc).splitlines()[0]
        print(f"{command}: database unavailable: {reason}", file=sys.stderr)
        return INFRASTRUCTURE_FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    engine = create_engine(database_url())
    try:
        exit_code = _guarded(
            "recon-import",
            lambda: cli.run(
                argv,
                lambda: ImportExport(
                    SqlAlchemyIngestionUnitOfWork(
                        sessionmaker(engine), actor=Actor.system("recon-import")
                    ),
                    SystemClock(),
                    UuidIdGenerator(),
                ),
            ),
        )
        return _dispatch(engine, "recon-import", exit_code)
    finally:
        engine.dispose()


def reference_main(argv: Sequence[str] | None = None) -> int:
    engine = create_engine(database_url())
    try:
        return _guarded(
            "recon-reference",
            lambda: run_reference(
                argv,
                lambda: LoadReferenceData(
                    SqlAlchemyReconciliationUnitOfWork(
                        sessionmaker(engine), actor=Actor.system("recon-reference")
                    ),
                    UuidIdGenerator(),
                ),
            ),
        )
    finally:
        engine.dispose()


def reconcile_main(argv: Sequence[str] | None = None) -> int:
    engine = create_engine(database_url())
    try:
        exit_code = _guarded(
            "recon-reconcile",
            lambda: run_reconcile(
                argv,
                lambda: ReconcilePeriod(
                    SqlAlchemyReconciliationUnitOfWork(
                        sessionmaker(engine), actor=Actor.system("recon-reconcile")
                    ),
                    SystemClock(),
                    UuidIdGenerator(),
                ),
            ),
        )
        return _dispatch(engine, "recon-reconcile", exit_code)
    finally:
        engine.dispose()


def evaluate_main(argv: Sequence[str] | None = None) -> int:
    engine = create_engine(database_url())
    try:
        return _guarded(
            "recon-evaluate",
            lambda: run_evaluate(
                argv,
                lambda: EvaluateRun(
                    SqlAlchemyReconciliationUnitOfWork(
                        sessionmaker(engine), actor=Actor.system("recon-evaluate")
                    )
                ),
            ),
        )
    finally:
        engine.dispose()
