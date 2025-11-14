"""Winner selection helpers."""

from __future__ import annotations

from typing import Iterable, Optional

from ..bidders.client import BidResponse


def select_winner(bids: Iterable[BidResponse]) -> Optional[BidResponse]:
    return max(bids, key=lambda bid: bid.price, default=None)