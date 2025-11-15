"""Admin health endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def health(request: Request) -> dict[str, int | str]:
    start_time = getattr(request.app.state, "start_time", None)
    if start_time:
        uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    else:
        uptime = 0
    settings = request.app.state.server_config
    return {
        "status": "healthy",
        "uptime_seconds": uptime,
        "version": request.app.version,
        "auction_window_ms": settings.auction.window_ms,
    }
