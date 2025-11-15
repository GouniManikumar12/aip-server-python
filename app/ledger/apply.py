"""Ledger service that persists context, bids, winners, and events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..auction.models import BidResponse
from ..storage import LedgerStorage
from .billing import clearing_price
from .fsm import LedgerEvent, LedgerState, transition


@dataclass
class LedgerService:
    storage: LedgerStorage

    async def create_record(self, context_request: dict[str, Any]) -> dict[str, Any]:
        auction_id = context_request.get("request_id") or str(uuid.uuid4())
        token_hint = context_request.get("serve_token_hint")
        serve_token = (
            f"{token_hint}-{uuid.uuid4().hex[:8]}"
            if token_hint
            else f"stk_{uuid.uuid4().hex}"
        )
        record = {
            "record_id": serve_token,
            "serve_token": serve_token,
            "auction_id": auction_id,
            "state": LedgerState.CREATED.value,
            "context": context_request,
            "bids": [],
            "winner": None,
            "events": [],
            "no_bid": False,
            "pools": [],
            "eligible_bidders": [],
        }
        return await self.storage.create_record(record)

    async def settle_auction(
        self,
        record_id: str,
        bids: list[BidResponse],
        winner: BidResponse | None,
    ) -> dict[str, Any]:
        record = await self.storage.get_record(record_id)
        new_state = transition(LedgerState(record["state"]), LedgerEvent.AUCTION_SETTLED)
        payload = {
            "state": new_state.value,
            "bids": [bid.payload for bid in bids],
            "winner": winner.payload if winner else None,
            "clearing_price": clearing_price(bids, winner),
        }
        return await self.storage.update_record(record_id, payload)

    async def record_event(self, record_id: str, event_payload: dict[str, Any]) -> dict[str, Any]:
        record = await self.storage.get_record(record_id)
        payload: dict[str, Any] = {}
        try:
            new_state = transition(LedgerState(record["state"]), LedgerEvent.EVENT_INGESTED)
            payload["state"] = new_state.value
        except ValueError:
            new_state = LedgerState(record["state"])
        if payload:
            await self.storage.update_record(record_id, payload)
        return await self.storage.append_event(record_id, event_payload)

    async def record_no_bid(self, record_id: str) -> dict[str, Any]:
        return await self.storage.update_record(
            record_id,
            {
                "state": LedgerState.NO_BID.value,
                "no_bid": True,
                "bids": [],
                "winner": None,
                "clearing_price": 0.0,
            },
        )

    async def annotate_record(self, record_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return await self.storage.update_record(record_id, updates)

    async def get_record(self, record_id: str) -> dict[str, Any]:
        return await self.storage.get_record(record_id)

    async def list_records(self) -> list[dict[str, Any]]:
        return await self.storage.list_records()
