"""Expose currently loaded server config for debugging."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..config import ServerConfig

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_config(request: Request) -> ServerConfig:
    return request.app.state.server_config


@router.get("/config")
async def config(config: ServerConfig = Depends(_get_config)) -> dict:
    return {
        "listen": dict(config.listen),
        "transport": {
            "nonce_ttl_seconds": config.transport.nonce_ttl_seconds,
            "max_clock_skew_ms": config.transport.max_clock_skew_ms,
        },
        "ledger": {
            "backend": config.ledger.backend,
            "options": dict(config.ledger.options),
        },
    }
