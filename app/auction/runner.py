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
        serve_token = record["serve_token"]
        auction_id = record["auction_id"]
        pools = self._classify_pools(context_request)
        eligible_bidders = self._registry.filter_by_pools(pools)
        eligible_names = [bidder.name for bidder in eligible_bidders]
        await self._ledger.annotate_record(
            serve_token,
            {
                "pools": pools,
                "eligible_bidders": eligible_names,
            },
        )
        await self._inbox.register(serve_token, eligible_names)
        publish_payload = {
            "auction_id": auction_id,
            "serve_token": serve_token,
            "pools": pools,
            "context_request": context_request,
            "bidders": eligible_names,
        }
        await self._fanout.publish(auction_id, pools, publish_payload)
        bids = await self._inbox.collect(serve_token, self._window_ms)
        if not bids:
            return await self._ledger.record_no_bid(serve_token)
        winner = select_winner(bids)
        result = await self._ledger.settle_auction(serve_token, bids, winner)
        return result

    def _classify_pools(self, context_request: dict[str, Any]) -> list[str]:
        candidates: list[Any] = [
            context_request.get("category_pools"),
            context_request.get("categories"),
            context_request.get("pools"),
        ]
        context = context_request.get("context")
        if isinstance(context, dict):
            candidates.extend(
                [
                    context.get("category_pools"),
                    context.get("categories"),
                    context.get("pools"),
                ]
            )
        features = context_request.get("features")
        if isinstance(features, dict):
            candidates.append(features.get("topic"))
        pools: Any = next((value for value in candidates if value), None)
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
