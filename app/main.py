from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from jsonschema import ValidationError

from .admin import config as admin_config
from .admin import health as admin_health
from .admin import stats as admin_stats
from .auction.runner import AuctionRunner
from .bidders.client import BidderClient
from .bidders.registry import BidderRegistry
from .config import ServerConfig, get_bidder_config_path, get_server_config
from .events.anti_replay import EventReplayGuard
from .events.handler import EventService
from .ledger.apply import LedgerService
from .storage import LedgerStorage, build_storage
from .transport.nonces import NonceCache
from .validation.validator import SchemaRegistry, get_schema_registry
from .auction.fanout import BidFanout


@asynccontextmanager
async def lifespan(app: FastAPI):
    server_config = get_server_config()
    schema_registry = get_schema_registry()
    bidder_registry = BidderRegistry(get_bidder_config_path())
    nonce_cache = NonceCache(server_config.transport.nonce_ttl_seconds)
    storage = build_storage(server_config)
    ledger_service = LedgerService(storage)
    replay_guard = EventReplayGuard()
    bidder_client = BidderClient(
        max_skew_ms=server_config.transport.max_clock_skew_ms,
        nonce_cache=nonce_cache,
    )
    fanout = BidFanout(bidder_client)
    auction_runner = AuctionRunner(bidder_registry, fanout, ledger_service)
    event_service = EventService(ledger_service, replay_guard)

    app.state.server_config = server_config
    app.state.schema_registry = schema_registry
    app.state.bidder_registry = bidder_registry
    app.state.nonce_cache = nonce_cache
    app.state.storage = storage
    app.state.ledger = ledger_service
    app.state.bidder_client = bidder_client
    app.state.fanout = fanout
    app.state.auction_runner = auction_runner
    app.state.event_service = event_service

    try:
        yield
    finally:
        await bidder_client.close()


app = FastAPI(
    title="AIP Reference Server",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.include_router(admin_health.router)
app.include_router(admin_stats.router)
app.include_router(admin_config.router)


# Dependency helpers ---------------------------------------------------------


def get_server_settings(request: Request) -> ServerConfig:
    return request.app.state.server_config


def get_schema_service(request: Request) -> SchemaRegistry:
    return request.app.state.schema_registry


def get_auction_runner(request: Request) -> AuctionRunner:
    return request.app.state.auction_runner


def get_event_service(request: Request) -> EventService:
    return request.app.state.event_service


def get_ledger_service(request: Request) -> LedgerService:
    return request.app.state.ledger


def get_storage_backend(request: Request) -> LedgerStorage:
    return request.app.state.storage


def get_nonce_cache(request: Request) -> NonceCache:
    return request.app.state.nonce_cache


# Routes ---------------------------------------------------------------------


@app.get("/", tags=["meta"])
async def root(settings: ServerConfig = Depends(get_server_settings)) -> dict[str, Any]:
    return {
        "service": "aip-server",
        "transport": {
            "nonce_ttl_seconds": settings.transport.nonce_ttl_seconds,
            "max_clock_skew_ms": settings.transport.max_clock_skew_ms,
        },
    }


@app.post("/context", tags=["auction"])
async def run_auction(
    payload: dict[str, Any] = Body(...),
    runner: AuctionRunner = Depends(get_auction_runner),
    schemas: SchemaRegistry = Depends(get_schema_service),
) -> dict[str, Any]:
    try:
        schemas.validate("context_request", payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc.message)) from exc
    result = await runner.run(payload)
    return result


@app.post("/events/{event_type}", tags=["events"])
async def ingest_event(
    event_type: str,
    payload: dict[str, Any] = Body(...),
    event_service: EventService = Depends(get_event_service),
) -> dict[str, Any]:
    try:
        return await event_service.ingest(event_type, payload)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health", tags=["admin"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
