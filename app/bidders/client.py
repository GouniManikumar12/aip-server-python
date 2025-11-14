"""HTTP client for bidder fanout."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from ..transport.signatures import SignatureError, verify_signature
from ..transport.timestamps import TimestampError, assert_within_skew
from ..transport.nonces import NonceCache, NonceError
from .registry import BidderConfig


@dataclass
class BidResponse:
    bidder: str
    payload: dict[str, Any]
    price: float


class BidderClient:
    def __init__(self, *, max_skew_ms: int, nonce_cache: NonceCache) -> None:
        self._client = httpx.AsyncClient()
        self._max_skew_ms = max_skew_ms
        self._nonce_cache = nonce_cache
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def request_bid(self, bidder: BidderConfig, payload: dict[str, Any]) -> BidResponse | None:
        try:
            response = await self._client.post(
                bidder.endpoint,
                json=payload,
                timeout=bidder.timeout_ms / 1000,
            )
            response.raise_for_status()
            data = response.json()
            await self._enforce_transport_guards(data, bidder.public_key)
            price = float(data.get("price", 0))
            return BidResponse(bidder=bidder.name, payload=data, price=price)
        except (httpx.HTTPError, SignatureError, TimestampError, NonceError, ValueError):
            return None

    async def _enforce_transport_guards(self, payload: dict[str, Any], public_key: str) -> None:
        timestamp = payload.get("timestamp")
        nonce = payload.get("nonce")
        await self._nonce_cache.assert_fresh(f"{payload.get('bid_id')}:{nonce}")
        assert_within_skew(timestamp, max_skew_ms=self._max_skew_ms)
        verify_signature(payload.get("payload", payload), payload.get("signature", ""), public_key)

    @property
    def canonical_client(self) -> httpx.AsyncClient:
        return self._client
