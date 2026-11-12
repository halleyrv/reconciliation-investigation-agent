"""Use case: reconcile a period. Idempotent by (period, ruleset version), all or nothing."""

from contextlib import ExitStack, suppress
from datetime import date

from recon.reconciliation.application.ports import ReconciliationUnitOfWork, RunLiveness
from recon.reconciliation.domain.calendar import BusinessCalendar
from recon.reconciliation.domain.engine import MatchingEngine, default_engine
from recon.reconciliation.domain.events import DiscrepancyDetected
from recon.reconciliation.domain.results import Period
from recon.reconciliation.domain.rules import Ruleset
from recon.reconciliation.domain.run import InvalidRunTransition, ReconciliationRun, RunStatus
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.ports import Clock, IdGenerator

# The rules in force. Change it whenever a rule or its reference data changes meaning.
RULESET_VERSION = "v1"
# Settlement policy of the gateways (simulator policies/settlement_policy.md).
SETTLEMENT_LAG_BUSINESS_DAYS = 2
# shortcut: single currency in v1 (ADR-0002); take it from the records when a second arrives.
CURRENCY = "USD"


class RunInProgress(Exception):
    """A live process is still running this period and ruleset."""

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


class PeriodNotClosed(Exception):
    """The bank data does not reach the period's last payout due date yet (T+lag), or a gap
    between its bank statements stops it before (ADR-0020): running
    now would freeze false ``missing_in_bank`` findings for its last batches."""

    def __init__(self, period: Period, latest: date | None, due: date) -> None:
        reach = f"bank data reaches {latest}" if latest else "no bank data is imported"
        super().__init__(
            f"{period.start} to {period.end} is not closed: {reach}, its last payouts are"
            f" due {due}; import the bank statements first"
        )


class MissingReferenceData(Exception):
    """The run would report fees or delays it cannot check; load the reference data first."""


class ReconcilePeriod:
    def __init__(
        self,
        uow: ReconciliationUnitOfWork,
        liveness: RunLiveness,
        clock: Clock,
        ids: IdGenerator,
        engine: MatchingEngine | None = None,
    ) -> None:
        self._uow = uow
        self._liveness = liveness
        self._clock = clock
        self._ids = ids
        self._engine = engine or default_engine()

    def __call__(self, period: Period, ruleset_version: str = RULESET_VERSION) -> ReconciliationRun:
        """Return the completed run of the period, or start one and record its whole output.

        A run that fails leaves status ``failed`` and nothing else (its transaction rolls
        back) and ``RunFailed`` is raised from the cause; a later call starts a new run. A
        run still running raises ``RunInProgress``, an overlapping one ``PeriodOverlaps``.
        A run whose process died is failed first, so it blocks nothing (B7).
        """
        self._fail_dead_runs(period, ruleset_version)
        with ExitStack() as alive:
            return self._run(period, ruleset_version, alive)

    def _fail_dead_runs(self, period: Period, ruleset_version: str) -> None:
        """Committed on its own: a dead run is failed even when the new run is then refused."""
        with self._uow as uow:
            uow.runs.lock(period, ruleset_version)
            for run in uow.runs.running(ruleset_version):
                if not self._liveness.is_alive(run.id):
                    # it may have finished between the read and the check: nothing to recover
                    with suppress(InvalidRunTransition):
                        uow.runs.save(run.failed(self._clock.now()))
            uow.commit()

    def _run(self, period: Period, ruleset_version: str, alive: ExitStack) -> ReconciliationRun:
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
            due = _last_due_date(period, uow.reference.holidays())
            calendar = BusinessCalendar(uow.reference.holidays())
            latest = _bank_reach(uow.sources.bank_statements(), period.start, calendar)
            if latest is None or latest < due:
                raise PeriodNotClosed(period, latest, due)
            run = ReconciliationRun.start(
                self._ids.new(), period, ruleset_version, self._clock.now()
            )
            uow.runs.add(run)
            # alive before it is committed: nobody sees it running with no live process
            alive.enter_context(self._liveness.hold(run.id))
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
    # The period's last payouts can fall due in the next year: its calendar is needed too.
    last_due = _last_due_date(period, ruleset.calendar.holidays)
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


def _bank_reach(
    statements: list[tuple[date, date]], start: date, calendar: BusinessCalendar
) -> date | None:
    """How far the bank statements reach without a gap from the period start (ADR-0020): a
    business day no statement covers stops the reach, whatever later statements hold."""
    reach: date | None = None
    for first, last in sorted(statements):
        if reach is not None and reach >= start and first > calendar.add_business_days(reach, 1):
            break
        reach = last if reach is None else max(reach, last)
    return reach


def _last_due_date(period: Period, holidays: frozenset[date]) -> date:
    """When the payout of the period's last batch is due. A year whose holidays are not
    loaded counts as having none; the reference check then fails the run for that year."""
    return BusinessCalendar(holidays).add_business_days(period.end, SETTLEMENT_LAG_BUSINESS_DAYS)
