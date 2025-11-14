"""Ledger finite state machine."""

from __future__ import annotations

from enum import Enum


class LedgerState(str, Enum):
    CREATED = "created"
    AUCTION_COMPLETED = "auction_completed"
    EVENT_RECORDED = "event_recorded"


class LedgerEvent(str, Enum):
    AUCTION_SETTLED = "auction_settled"
    EVENT_INGESTED = "event_ingested"


_TRANSITIONS = {
    (LedgerState.CREATED, LedgerEvent.AUCTION_SETTLED): LedgerState.AUCTION_COMPLETED,
    (
        LedgerState.AUCTION_COMPLETED,
        LedgerEvent.EVENT_INGESTED,
    ): LedgerState.EVENT_RECORDED,
}


def transition(current: LedgerState, event: LedgerEvent) -> LedgerState:
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as exc:
        raise ValueError(f"invalid transition from {current} via {event}") from exc
