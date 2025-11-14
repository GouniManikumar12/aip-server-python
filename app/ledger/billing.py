"""Billing utilities such as clearing price calculation."""

from __future__ import annotations

from typing import Iterable

from ..bidders.client import BidResponse


def clearing_price(bids: Iterable[BidResponse], winner: BidResponse | None) -> float:
    if not winner:
        return 0.0
    sorted_bids = sorted(bids, key=lambda bid: bid.price, reverse=True)
    if len(sorted_bids) < 2:
        return winner.price
    return sorted_bids[1].price
