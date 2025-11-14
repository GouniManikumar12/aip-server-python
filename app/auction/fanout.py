"""Bidder fanout orchestration."""

from __future__ import annotations

import asyncio
from typing import Iterable

from ..bidders.client import BidderClient, BidResponse
from ..bidders.registry import BidderConfig


class BidFanout:
    def __init__(self, client: BidderClient) -> None:
        self._client = client

    async def gather(self, bidders: Iterable[BidderConfig], payload: dict) -> list[BidResponse]:
        tasks = [self._client.request_bid(bidder, payload) for bidder in bidders]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return [bid for bid in results if bid]
