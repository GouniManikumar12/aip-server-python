"""Glue between fanout, selection, and ledger persistence."""

from __future__ import annotations

from typing import Any

from ..bidders.registry import BidderRegistry
from ..ledger.apply import LedgerService
from .fanout import BidFanout
from .selection import select_winner
from .models import BidResponse
from ..events.handler import BidResponseInbox


class AuctionRunner:
    def __init__(
        self,
        registry: BidderRegistry,
        fanout: BidFanout,
        ledger: LedgerService,
        inbox: BidResponseInbox,
        window_ms: int,
    ) -> None:
        self._registry = registry
        self._fanout = fanout
        self._ledger = ledger
        self._inbox = inbox
        self._window_ms = window_ms

    async def run(self, context_request: dict[str, Any]) -> dict[str, Any]:
        record = await self._ledger.create_record(context_request)
        pools = self._classify_pools(context_request)
        eligible_bidders = self._registry.filter_by_pools(pools)
        await self._inbox.register(record["record_id"], [bidder.name for bidder in eligible_bidders])
        publish_payload = {
            "auction_id": record["record_id"],
            "pools": pools,
            "context_request": context_request,
            "bidders": [bidder.name for bidder in eligible_bidders],
        }
        await self._fanout.publish(record["record_id"], pools, publish_payload)
        bids = await self._inbox.collect(record["record_id"], self._window_ms)
        if not bids:
            return await self._ledger.record_no_bid(record["record_id"])
        winner = select_winner(bids)
        result = await self._ledger.settle_auction(record["record_id"], bids, winner)
        return result

    def _classify_pools(self, context_request: dict[str, Any]) -> list[str]:
        pools = context_request.get("category_pools") or context_request.get("categories")
        if not pools:
            context = context_request.get("context", {}) if isinstance(context_request.get("context"), dict) else {}
            pools = context.get("categories")
        if not pools:
            return ["default"]
        if isinstance(pools, str):
            return [pools]
        ordered = []
        seen: set[str] = set()
        for pool in pools:
            if pool not in seen:
                ordered.append(pool)
                seen.add(pool)
        return ordered or ["default"]
