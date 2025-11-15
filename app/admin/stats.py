"""Operational stats endpoint."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..bidders.registry import BidderRegistry
from ..ledger.apply import LedgerService

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_ledger(request: Request) -> LedgerService:
    return request.app.state.ledger


def _get_bidder_registry(request: Request) -> BidderRegistry:
    return request.app.state.bidder_registry


@router.get("/stats")
async def stats(
    ledger: LedgerService = Depends(_get_ledger),
    registry: BidderRegistry = Depends(_get_bidder_registry),
) -> dict[str, Any]:
    records = await ledger.list_records()
    total_auctions = len(records)
    total_bids = sum(len(record.get("bids", [])) for record in records)
    no_bid_count = sum(1 for record in records if record.get("no_bid"))
    no_bid_rate = (no_bid_count / total_auctions) if total_auctions else 0.0

    bids_by_bidder: Counter[str] = Counter()
    wins_by_bidder: Counter[str] = Counter()
    invited_by_bidder: Counter[str] = Counter()
    pool_distribution: Counter[str] = Counter()

    for record in records:
        for pool in record.get("pools", []):
            pool_distribution[pool] += 1
        for bidder in record.get("eligible_bidders", []):
            invited_by_bidder[bidder] += 1
        for bid in record.get("bids", []):
            bidder_name = _bidder_from_payload(bid)
            if bidder_name:
                bids_by_bidder[bidder_name] += 1
        winner_payload = record.get("winner")
        if winner_payload:
            bidder_name = _bidder_from_payload(winner_payload)
            if bidder_name:
                wins_by_bidder[bidder_name] += 1

    bidder_success_rates = {
        bidder: round(wins_by_bidder[bidder] / bids_by_bidder[bidder], 4)
        for bidder in bids_by_bidder
        if bids_by_bidder[bidder]
    }
    bidder_timeout_rates = {}
    for bidder in registry.all():
        invitations = invited_by_bidder.get(bidder.name, 0)
        responses = bids_by_bidder.get(bidder.name, 0)
        timeout_rate = 0.0
        if invitations:
            timeout_rate = round(max(invitations - responses, 0) / invitations, 4)
        bidder_timeout_rates[bidder.name] = timeout_rate

    return {
        "total_auctions": total_auctions,
        "total_bids": total_bids,
        "no_bid_rate": round(no_bid_rate, 4),
        "bidder_success_rates": bidder_success_rates,
        "bidder_timeout_rates": bidder_timeout_rates,
        "pool_distribution": dict(pool_distribution),
    }


def _bidder_from_payload(payload: dict[str, Any]) -> str | None:
    bid = payload.get("bid") if isinstance(payload, dict) else None
    if isinstance(bid, dict):
        payload = bid
    return payload.get("brand_agent_id") or payload.get("agent_id") or payload.get("bidder")
