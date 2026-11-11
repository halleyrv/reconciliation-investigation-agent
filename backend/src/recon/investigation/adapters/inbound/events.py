"""Inbound event handlers: Reconciliation's events translated into Investigation commands
(anti-corruption layer, bounded-contexts.md)."""

import uuid
from collections.abc import Callable

from recon.investigation.application.open_case import OpenCase
from recon.shared_kernel.events import OutboxMessage


def on_discrepancy_detected(open_case: OpenCase) -> Callable[[OutboxMessage], None]:
    """``DiscrepancyDetected`` opens its discrepancy's case; a redelivery finds it open."""

    def handle(message: OutboxMessage) -> None:
        open_case(uuid.UUID(str(message.payload["discrepancy_id"])))

    return handle
