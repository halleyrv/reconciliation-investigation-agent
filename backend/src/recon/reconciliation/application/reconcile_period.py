"""Use case: reconcile a period. Idempotent by (period, ruleset version), all or nothing."""

from datetime import timedelta

from recon.reconciliation.application.ports import ReconciliationUnitOfWork
from recon.reconciliation.domain.calendar import BusinessCalendar
from recon.reconciliation.domain.engine import MatchingEngine, default_engine
from recon.reconciliation.domain.events import DiscrepancyDetected
from recon.reconciliation.domain.results import Period
from recon.reconciliation.domain.rules import Ruleset
from recon.reconciliation.domain.run import ReconciliationRun, RunStatus
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.ports import Clock, IdGenerator

# The rules in force. Change it whenever a rule or its reference data changes meaning.
RULESET_VERSION = "v1"
# Settlement policy of the gateways (simulator policies/settlement_policy.md).
SETTLEMENT_LAG_BUSINESS_DAYS = 2
# Calendar days that always hold the settlement lag in business days, holidays included.
DUE_DATE_MARGIN_DAYS = 14
# shortcut: single currency in v1 (ADR-0002); take it from the records when a second arrives.
CURRENCY = "USD"


class RunInProgress(Exception):
    """A run of this period and ruleset is still running, or was left running by a crash."""

    def __init__(self, run: ReconciliationRun) -> None:
        super().__init__(f"run {run.id} of {run.period} ({run.ruleset_version}) is still running")
        self.run = run


class PeriodOverlaps(Exception):
    """Another live run of the ruleset covers part of the period (ADR-0016)."""

    def __init__(self, period: Period, existing: ReconciliationRun) -> None:
        super().__init__(
            f"{period.start} to {period.end} overlaps run {existing.id}"
            f" ({existing.period.start} to {existing.period.end})"
        )


class RunFailed(Exception):
    """The run started and failed; it is recorded as ``failed`` with no output."""

    def __init__(self, run: ReconciliationRun, cause: Exception) -> None:
        super().__init__(f"run {run.id} failed: {cause}")
        self.run = run


class MissingReferenceData(Exception):
    """The run would report fees or delays it cannot check; load the reference data first."""


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
        """Return the completed run of the period, or start one and record its whole output.

        A run that fails leaves status ``failed`` and nothing else (its transaction rolls
        back) and ``RunFailed`` is raised from the cause; a later call starts a new run. A
        run still running raises ``RunInProgress``, an overlapping one ``PeriodOverlaps``.
        """
        with self._uow as uow:
            uow.runs.lock(period, ruleset_version)
            existing = uow.runs.find_live(period, ruleset_version)
            if existing is not None and existing.status is RunStatus.RUNNING:
                raise RunInProgress(existing)
            if existing is not None:
                return existing
            overlapping = uow.runs.find_overlapping(period, ruleset_version)
            if overlapping is not None:
                raise PeriodOverlaps(period, overlapping)
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
        except Exception as error:
            failure = RunFailed(run, error)
            try:
                with self._uow as uow:
                    uow.runs.save(run.failed(self._clock.now()))
                    uow.commit()
            except Exception as marking:  # e.g. the database that broke the run is still gone
                failure.add_note(f"run {run.id} could not be marked failed: {marking!r}")
            raise failure from error
        return done

    def _record_output(self, uow: ReconciliationUnitOfWork, run: ReconciliationRun) -> None:
        snapshot = uow.sources.snapshot(CURRENCY)
        ruleset = Ruleset(
            fee_schedules=uow.reference.fee_schedules(),
            calendar=BusinessCalendar(uow.reference.holidays()),
            settlement_lag_business_days=SETTLEMENT_LAG_BUSINESS_DAYS,
        )
        _require_reference_data(snapshot, ruleset, uow.reference.calendar_years(), run.period)
        result = self._engine.run(snapshot, ruleset, run.period)
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


def _require_reference_data(
    snapshot: Snapshot, ruleset: Ruleset, calendar_years: frozenset[int], period: Period
) -> None:
    """Principle 10: never report fees or settlement dates as clean without the data to check."""
    # Due dates of the period's last batches can fall in the next year: cover them too.
    last_due = period.end + timedelta(days=DUE_DATE_MARGIN_DAYS)
    missing_years = sorted(set(range(period.start.year, last_due.year + 1)) - calendar_years)
    if missing_years:
        years = ", ".join(map(str, missing_years))
        raise MissingReferenceData(f"no bank holiday calendar for {years}; load it first")
    unscheduled = sorted(
        (payment.captured_at.date(), fee.gateway, fee.fee_type)
        for fee in snapshot.fees
        if (day := snapshot.anchor_of(fee.ref)) is not None
        and period.start <= day <= period.end
        and (payment := snapshot.payments_by_id.get(fee.payment_ref)) is not None
        and ruleset.schedule_for(fee.gateway, fee.fee_type, payment.captured_at.date()) is None
    )
    if unscheduled:
        day, gateway, fee_type = unscheduled[0]
        raise MissingReferenceData(
            f"no fee schedule for {gateway} {fee_type} on {day}"
            f" ({len(unscheduled)} fees unchecked); load it first"
        )
