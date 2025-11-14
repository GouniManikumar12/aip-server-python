"""Glue between fanout, selection, and ledger persistence."""

from __future__ import annotations

from typing import Any

from ..bidders.registry import BidderRegistry
from ..ledger.apply import LedgerService
from .fanout import BidFanout
from .selection import select_winner


class AuctionRunner:
    def __init__(self, registry: BidderRegistry, fanout: BidFanout, ledger: LedgerService) -> None:
        self._registry = registry
        self._fanout = fanout
        self._ledger = ledger

    async def run(self, context_request: dict[str, Any]) -> dict[str, Any]:
        record = await self._ledger.create_record(context_request)
        bids = await self._fanout.gather(self._registry.all(), context_request)
        winner = select_winner(bids)
        result = await self._ledger.settle_auction(record["record_id"], bids, winner)
        return result
