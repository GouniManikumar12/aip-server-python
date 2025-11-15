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

EVENT_PRIORITY = {
    "cpx_exposure": 0,
    "cpc_click": 1,
    "cpa_conversion": 2,
}


class EventService:
    def __init__(
        self,
        ledger: LedgerService,
        replay_guard: EventReplayGuard,
        *,
        max_skew_ms: int,
    ) -> None:
        self._ledger = ledger
        self._guard = replay_guard
        self._max_skew_ms = max_skew_ms

    async def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = payload.get("event_type")
        if not event_type:
            raise ValueError("event_type is required")
        validate_event(event_type, payload)
        serve_token = payload.get("serve_token")
        if not serve_token:
            raise ValueError("serve_token is required")
        timestamp = payload.get("ts")
        if not timestamp:
            raise ValueError("ts is required")
        assert_within_skew(timestamp, max_skew_ms=self._max_skew_ms)
        await self._guard.assert_unique(self._replay_key(payload))
        try:
            record = await self._ledger.get_record(serve_token)
        except KeyError as exc:
            raise ValueError("unknown serve_token") from exc
        if record.get("no_bid"):
            raise ValueError("cannot ingest events for no-bid auction")
        self._assert_single_charge(record, event_type)
        signature_payload = self._extract_signed_payload(payload)
        try:
            verify_signature(
                signature_payload,
                payload.get("signature", ""),
                payload.get("public_key", ""),
            )
        except SignatureError as exc:  # pragma: no cover - crypto errors delegated
            raise ValueError(str(exc)) from exc
        return await self._ledger.record_event(serve_token, payload)

    def _assert_single_charge(self, record: dict[str, Any], event_type: str) -> None:
        existing_events = record.get("events", [])
        highest = -1
        for event in existing_events:
            priority = EVENT_PRIORITY.get(event.get("event_type", ""), -1)
            highest = max(highest, priority)
        current_priority = EVENT_PRIORITY.get(event_type, -1)
        if current_priority <= highest:
            raise ValueError("event violates single-charge rule")

    def _extract_signed_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = payload.get("payload")
        if envelope is not None:
            return envelope
        return {k: v for k, v in payload.items() if k not in {"signature", "public_key"}}

    def _replay_key(self, payload: dict[str, Any]) -> str:
        serve_token = payload.get("serve_token", "")
        event_type = payload.get("event_type", "")
        unique_component = (
            payload.get("event_id")
            or payload.get("conversion_id")
            or payload.get("ts")
            or ""
        )
        return f"{serve_token}:{event_type}:{unique_component}"


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
            if allowed is None:
                raise PermissionError("serve_token is not active")
            if response.bidder not in allowed:
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
        serve_token = payload.get("serve_token") or payload.get("auction_id")
        if not serve_token:
            raise ValueError("serve_token is required")
        bid_payload = payload.get("bid")
        if not isinstance(bid_payload, dict):
            raise ValueError("bid payload is required")
        bidder_name = (
            bid_payload.get("brand_agent_id")
            or payload.get("brand_agent_id")
            or bid_payload.get("bidder")
            or payload.get("bidder")
        )
        if not bidder_name:
            raise ValueError("brand_agent_id is required")
        bidder = self.registry.get(bidder_name)
        if not bidder:
            raise ValueError("unknown bidder")
        timestamp = payload.get("timestamp") or bid_payload.get("timestamp")
        if not timestamp:
            raise ValueError("timestamp is required")
        auth = bid_payload.get("auth") or {}
        nonce = auth.get("nonce") or payload.get("nonce")
        if not nonce:
            raise ValueError("nonce is required")
        signature = payload.get("signature") or auth.get("signature") or ""
        await self.nonce_cache.assert_fresh(f"{serve_token}:{nonce}:{bidder_name}")
        assert_within_skew(timestamp, max_skew_ms=self.max_skew_ms)
        try:
            verify_signature(bid_payload, signature, bidder.public_key)
        except SignatureError as exc:  # pragma: no cover - delegated to crypto lib
            raise ValueError(str(exc)) from exc
        price_value = self._derive_price(bid_payload)
        response_payload = {
            "serve_token": serve_token,
            "bid": bid_payload,
            "timestamp": timestamp,
            "signature": signature,
        }
        response = BidResponse(bidder=bidder.name, payload=response_payload, price=price_value)
        try:
            await self.inbox.add(serve_token, response)
        except PermissionError as exc:  # pragma: no cover - simple guard
            raise ValueError(str(exc)) from exc

    def _derive_price(self, bid_payload: dict[str, Any]) -> float:
        pricing = bid_payload.get("pricing") or {}
        candidates = [
            pricing.get("cpa"),
            pricing.get("CPA"),
            pricing.get("cpc"),
            pricing.get("CPC"),
            pricing.get("cpx"),
            pricing.get("CPX"),
            bid_payload.get("price"),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                return float(candidate)
            except (TypeError, ValueError):
                continue
        raise ValueError("pricing missing valid entries")
