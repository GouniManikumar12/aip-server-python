"""Expose currently loaded server config for debugging."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..bidders.registry import BidderRegistry
from ..config import ServerConfig

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_config(request: Request) -> ServerConfig:
    return request.app.state.server_config


def _get_bidder_registry(request: Request) -> BidderRegistry:
    return request.app.state.bidder_registry


@router.get("/config")
async def config(
    request: Request,
    config: ServerConfig = Depends(_get_config),
    registry: BidderRegistry = Depends(_get_bidder_registry),
) -> dict:
    pools: dict[str, list[str]] = {}
    for bidder in registry.all():
        for pool in bidder.pools:
            pools.setdefault(pool, []).append(bidder.name)
    pool_definitions = [
        {"name": name, "bidders": sorted(names), "active": bool(names)}
        for name, names in sorted(pools.items())
    ]
    distribution = config.auction.distribution
    return {
        "auction_window_ms": config.auction.window_ms,
        "pool_definitions": pool_definitions,
        "pubsub_provider": distribution.get("backend", "local"),
        "version": request.app.version,
        "storage_backend": config.ledger.backend,
    }
