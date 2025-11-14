"""Shared auction data structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BidResponse:
    bidder: str
    payload: dict[str, Any]
    price: float
