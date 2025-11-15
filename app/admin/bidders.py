"""Expose bidder registry information."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ..bidders.registry import BidderRegistry

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_registry(request: Request) -> BidderRegistry:
    return request.app.state.bidder_registry


@router.get("/bidders")
async def bidders(registry: BidderRegistry = Depends(_get_registry)) -> list[dict[str, Any]]:
    inventory = []
    for bidder in registry.all():
        inventory.append(
            {
                "id": bidder.name,
                "endpoint": bidder.endpoint,
                "pools": list(bidder.pools),
                "permissions": ["submit-bid"],
                "status": "active",
            }
        )
    return inventory
