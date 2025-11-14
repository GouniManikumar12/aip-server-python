"""Event ingestion and bid-response services."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from ..auction.models import BidResponse
from ..bidders.registry import BidderRegistry
from ..ledger.apply import LedgerService
from ..transport.nonces import NonceCache
from ..transport.signatures import SignatureError, verify_signature
from ..transport.timestamps import assert_within_skew
from .anti_replay import EventReplayGuard
from .validators import validate_event


class EventService:
    def __init__(self, ledger: LedgerService, replay_guard: EventReplayGuard) -> None:
        self._ledger = ledger
        self._guard = replay_guard

    async def ingest(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        validate_event(event_type, payload)
        record_id = payload.get("record_id")
        if not record_id:
            raise ValueError("record_id missing")
        await self._guard.assert_unique(payload.get("event_id"))
        return await self._ledger.record_event(record_id, payload)


class BidResponseInbox:
    def __init__(self) -> None:
        self._responses: dict[str, list[BidResponse]] = defaultdict(list)
        self._allowed: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(self, auction_id: str, bidders: Iterable[str]) -> None:
        async with self._lock:
            self._allowed[auction_id] = set(bidders)

    async def add(self, auction_id: str, response: BidResponse) -> None:
        async with self._lock:
            allowed = self._allowed.get(auction_id)
            if allowed is not None and response.bidder not in allowed:
                raise PermissionError("bidder is not subscribed to this auction")
            self._responses[auction_id].append(response)

    async def collect(self, auction_id: str, window_ms: int) -> list[BidResponse]:
        await asyncio.sleep(window_ms / 1000)
        async with self._lock:
            responses = self._responses.pop(auction_id, [])
            self._allowed.pop(auction_id, None)
            return responses


@dataclass
class BidResponseService:
    registry: BidderRegistry
    inbox: BidResponseInbox
    nonce_cache: NonceCache
    max_skew_ms: int

    async def submit(self, payload: dict[str, Any]) -> None:
        auction_id = payload.get("auction_id")
        bidder_name = payload.get("bidder")
        price = payload.get("price")
        if not auction_id or not bidder_name:
            raise ValueError("auction_id and bidder are required")
        bidder = self.registry.get(bidder_name)
        if not bidder:
            raise ValueError("unknown bidder")
        if price is None:
            raise ValueError("price is required")
        try:
            price_value = float(price)
        except (TypeError, ValueError) as exc:
            raise ValueError("price must be numeric") from exc
        timestamp = payload.get("timestamp")
        nonce = payload.get("nonce")
        signature = payload.get("signature", "")
        if not nonce:
            raise ValueError("nonce is required")
        if not timestamp:
            raise ValueError("timestamp is required")
        await self.nonce_cache.assert_fresh(f"{auction_id}:{nonce}:{bidder_name}")
        assert_within_skew(timestamp, max_skew_ms=self.max_skew_ms)
        try:
            verify_signature(payload.get("payload", payload), signature, bidder.public_key)
        except SignatureError as exc:  # pragma: no cover - delegated to crypto lib
            raise ValueError(str(exc)) from exc
        response = BidResponse(bidder=bidder.name, payload=payload, price=price_value)
        try:
            await self.inbox.add(auction_id, response)
        except PermissionError as exc:  # pragma: no cover - simple guard
            raise ValueError(str(exc)) from exc
