"""Inbound event handlers: Reconciliation's events translated into Investigation commands
(anti-corruption layer, bounded-contexts.md)."""

import uuid
from collections.abc import Callable
from contextlib import suppress

from recon.investigation.application.close_case import CloseSupersededCase
from recon.investigation.application.open_case import DiscrepancyRetired, OpenCase
from recon.shared_kernel.events import OutboxMessage


def on_discrepancy_detected(open_case: OpenCase) -> Callable[[OutboxMessage], None]:
    """``DiscrepancyDetected`` opens its discrepancy's case; a redelivery finds it open."""

    def handle(message: OutboxMessage) -> None:
        # a late delivery for a discrepancy a replacing run superseded: no case to open
        with suppress(DiscrepancyRetired):
            open_case(uuid.UUID(str(message.payload["discrepancy_id"])))

    return handle


def on_discrepancy_superseded(
    open_case: OpenCase, close_case: CloseSupersededCase
) -> Callable[[OutboxMessage], None]:
    """Found again: the case moves to its successor, as ``DiscrepancyDetected`` of the
    successor would do, whichever arrives first. Not found again: the case closes (D3)."""

    def handle(message: OutboxMessage) -> None:
        successor = message.payload["superseded_by"]
        if successor is None:
            close_case(uuid.UUID(str(message.payload["discrepancy_id"])))
        else:
            with suppress(DiscrepancyRetired):  # superseded in turn: its own event carries it
                open_case(uuid.UUID(str(successor)))

    return handle
