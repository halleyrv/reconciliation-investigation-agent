"""Use case: reconcile a period. Idempotent by (period, ruleset version), all or nothing."""

from recon.reconciliation.application.ports import ReconciliationUnitOfWork
from recon.reconciliation.domain.calendar import BusinessCalendar
from recon.reconciliation.domain.engine import MatchingEngine, default_engine
from recon.reconciliation.domain.events import DiscrepancyDetected
from recon.reconciliation.domain.results import Period
from recon.reconciliation.domain.rules import Ruleset
from recon.reconciliation.domain.run import ReconciliationRun
from recon.shared_kernel.ports import Clock, IdGenerator

# The rules in force. Change it whenever a rule or its reference data changes meaning.
RULESET_VERSION = "v1"
# Settlement policy of the gateways (simulator policies/settlement_policy.md).
SETTLEMENT_LAG_BUSINESS_DAYS = 2
# shortcut: single currency in v1 (ADR-0002); take it from the records when a second arrives.
CURRENCY = "USD"


class ReconcilePeriod:
    def __init__(
        self,
        uow: ReconciliationUnitOfWork,
        clock: Clock,
        ids: IdGenerator,
        engine: MatchingEngine | None = None,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids
        self._engine = engine or default_engine()

    def __call__(self, period: Period, ruleset_version: str = RULESET_VERSION) -> ReconciliationRun:
        """Return the live run of the period, or start one and record its whole output.

        A run that fails leaves status ``failed`` and nothing else (its transaction rolls
        back); the error is re-raised, and a later call starts a new run.
        """
        with self._uow as uow:
            uow.runs.lock(period, ruleset_version)
            existing = uow.runs.find_live(period, ruleset_version)
            if existing is not None:
                return existing
            run = ReconciliationRun.start(
                self._ids.new(), period, ruleset_version, self._clock.now()
            )
            uow.runs.add(run)
            uow.commit()
        try:
            with self._uow as uow:
                self._record_output(uow, run)
                done = run.completed(self._clock.now())
                uow.runs.save(done)
                uow.commit()
        except Exception:
            with self._uow as uow:
                uow.runs.save(run.failed(self._clock.now()))
                uow.commit()
            raise
        return done

    def _record_output(self, uow: ReconciliationUnitOfWork, run: ReconciliationRun) -> None:
        # shortcut: a run reconciles every ingested record and the period only names the run;
        # select records by settlement batch date when a second period is ingested (B4).
        snapshot = uow.sources.snapshot(CURRENCY)
        ruleset = Ruleset(
            fee_schedules=uow.reference.fee_schedules(),
            calendar=BusinessCalendar(uow.reference.holidays()),
            settlement_lag_business_days=SETTLEMENT_LAG_BUSINESS_DAYS,
        )
        result = self._engine.run(snapshot, ruleset)
        for group in result.groups:
            uow.results.add_group(run.id, self._ids.new(), group)
        now = self._clock.now()
        for discrepancy in result.discrepancies:
            discrepancy_id = self._ids.new()
            uow.results.add_discrepancy(run.id, discrepancy_id, discrepancy, run.period, now)
            uow.add_event(
                DiscrepancyDetected(
                    occurred_at=now,
                    discrepancy_id=discrepancy_id,
                    type=discrepancy.type.value,
                    delta_minor=discrepancy.delta_minor,
                    currency=discrepancy.actual.currency,
                )
            )
