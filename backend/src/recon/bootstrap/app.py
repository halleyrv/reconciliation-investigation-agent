"""The HTTP API: wires each context's routers to SQL units of work acting as ``system:api``."""

import logging

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from recon.bootstrap.outbox import default_relay, dispatch
from recon.bootstrap.problems import install_problem_handlers
from recon.bootstrap.settings import database_url, import_root
from recon.ingestion.adapters.inbound.http import imports_router
from recon.ingestion.adapters.outbound.sql import SqlAlchemyIngestionUnitOfWork
from recon.ingestion.application.get_import_batch import GetImportBatch
from recon.ingestion.application.import_export import ImportExport
from recon.investigation.adapters.inbound.http import cases_router
from recon.investigation.adapters.outbound.sql import (
    SqlAlchemyInvestigationUnitOfWork,
    SqlCaseQueries,
)
from recon.investigation.application.case_queries import GetCaseDetail, GetCaseHistory, ListCases
from recon.investigation.application.open_case import OpenCase
from recon.investigation.application.update_case import UpdateCase
from recon.reconciliation.adapters.inbound.http import runs_router
from recon.reconciliation.adapters.outbound.sql import (
    PostgresRunLiveness,
    SqlAlchemyReconciliationUnitOfWork,
    SqlRunQueries,
)
from recon.reconciliation.application.reconcile_period import ReconcilePeriod
from recon.reconciliation.application.run_queries import GetRunSummary, ListDiscrepancies
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.ports import SystemClock, UuidIdGenerator

logger = logging.getLogger(__name__)
API = Actor.system("api")  # ADR-0018


def create_app(engine: Engine | None = None) -> FastAPI:
    """``engine`` defaults to ``RECON_DATABASE_URL``; it connects on the first request."""
    engine = engine or create_engine(database_url())
    sessions = sessionmaker(engine)
    queries = SqlRunQueries(sessions)
    case_queries = SqlCaseQueries(sessions)

    def deliver_events() -> None:
        # like the CLI: a delivery problem is a warning and never changes the response
        for warning in dispatch(default_relay(engine)):
            logger.warning(warning)

    app = FastAPI(title="Reconciliation backend")
    install_problem_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # a use case per request: a unit of work holds one session and requests run in threads
    app.include_router(
        imports_router(
            lambda: ImportExport(
                SqlAlchemyIngestionUnitOfWork(sessions, actor=API),
                SystemClock(),
                UuidIdGenerator(),
            ),
            lambda: GetImportBatch(SqlAlchemyIngestionUnitOfWork(sessions, actor=API)),
            import_root(),
            deliver_events,
        )
    )
    app.include_router(
        runs_router(
            lambda: ReconcilePeriod(
                SqlAlchemyReconciliationUnitOfWork(sessions, actor=API),
                PostgresRunLiveness(engine),
                SystemClock(),
                UuidIdGenerator(),
            ),
            lambda: GetRunSummary(queries),
            lambda: ListDiscrepancies(queries),
            deliver_events,
        )
    )
    app.include_router(
        cases_router(
            lambda: OpenCase(
                SqlAlchemyInvestigationUnitOfWork(sessions, actor=API),
                SystemClock(),
                UuidIdGenerator(),
            ),
            lambda: GetCaseDetail(case_queries),
            lambda: ListCases(case_queries),
            lambda: GetCaseHistory(case_queries),
            # D2: the case update is the one endpoint acting as the user it names
            lambda actor: UpdateCase(
                SqlAlchemyInvestigationUnitOfWork(sessions, actor=actor), SystemClock()
            ),
            deliver_events,
        )
    )
    return app
