"""Use case: score the completed run of a period against a known answer (AC-2b.2)."""

from collections.abc import Iterable

from recon.reconciliation.application.evaluation import Evaluation, Finding, Link, evaluate
from recon.reconciliation.application.ports import ReconciliationUnitOfWork
from recon.reconciliation.application.reconcile_period import RULESET_VERSION
from recon.reconciliation.domain.results import Period
from recon.reconciliation.domain.run import ReconciliationRun, RunStatus


class NoCompletedRun(Exception):
    pass


class EvaluateRun:
    def __init__(self, uow: ReconciliationUnitOfWork) -> None:
        self._uow = uow

    def __call__(
        self,
        period: Period,
        expected: Iterable[Finding],
        expected_links: set[Link],
        ruleset_version: str = RULESET_VERSION,
    ) -> tuple[ReconciliationRun, Evaluation]:
        with self._uow as uow:
            run = uow.runs.find_live(period, ruleset_version)
            if run is None or run.status is not RunStatus.COMPLETED:
                raise NoCompletedRun(f"no completed {ruleset_version} run of {period}")
            findings = uow.outputs.findings(run.id)
            links = uow.outputs.links(run.id)
        return run, evaluate(expected, findings, expected_links, links)
