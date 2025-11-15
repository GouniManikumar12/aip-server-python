from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, status
from jsonschema import ValidationError

from .admin import bidders as admin_bidders
from .admin import config as admin_config
from .admin import health as admin_health
from .admin import stats as admin_stats
from .auction.runner import AuctionRunner
from .bidders.registry import BidderRegistry
from .config import ServerConfig, get_bidder_config_path, get_server_config
from .events.anti_replay import EventReplayGuard
from .events.handler import BidResponseInbox, BidResponseService, EventService
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
    distribution = server_config.auction.distribution
    fanout = BidFanout(
        backend=distribution.get("backend", "local"),
        options=distribution,
    )
    bid_inbox = BidResponseInbox()
    auction_runner = AuctionRunner(
        bidder_registry,
        fanout,
        ledger_service,
        bid_inbox,
        server_config.auction.window_ms,
    )
    event_service = EventService(
        ledger_service,
        replay_guard,
        max_skew_ms=server_config.transport.max_clock_skew_ms,
    )
    bid_response_service = BidResponseService(
        bidder_registry,
        bid_inbox,
        nonce_cache,
        server_config.transport.max_clock_skew_ms,
    )

    app.state.server_config = server_config
    app.state.schema_registry = schema_registry
    app.state.bidder_registry = bidder_registry
    app.state.nonce_cache = nonce_cache
    app.state.storage = storage
    app.state.ledger = ledger_service
    app.state.fanout = fanout
    app.state.auction_runner = auction_runner
    app.state.event_service = event_service
    app.state.bid_inbox = bid_inbox
    app.state.bid_response_service = bid_response_service
    app.state.start_time = datetime.now(timezone.utc)

    yield


app = FastAPI(
    title="AIP Reference Server",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.include_router(admin_health.router)
app.include_router(admin_stats.router)
app.include_router(admin_config.router)
app.include_router(admin_bidders.router)


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


def get_bid_response_service(request: Request) -> BidResponseService:
    return request.app.state.bid_response_service


# Routes ---------------------------------------------------------------------


@app.get("/", tags=["meta"])
async def root(settings: ServerConfig = Depends(get_server_settings)) -> dict[str, Any]:
    return {
        "service": "aip-server",
        "version": app.version,
        "transport": {
            "nonce_ttl_seconds": settings.transport.nonce_ttl_seconds,
            "max_clock_skew_ms": settings.transport.max_clock_skew_ms,
        },
        "auction": {
            "window_ms": settings.auction.window_ms,
            "distribution_backend": settings.auction.distribution.get("backend", "local"),
        },
    }


@app.get("/aip/ping", tags=["platform"])
async def ping() -> dict[str, Any]:
    return {"status": "ok", "version": app.version}


@app.post("/aip/context", tags=["platform"])
async def run_auction(
    payload: dict[str, Any] = Body(...),
    runner: AuctionRunner = Depends(get_auction_runner),
    schemas: SchemaRegistry = Depends(get_schema_service),
) -> dict[str, Any]:
    try:
        schemas.validate("platform_request", payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc.message)) from exc
    try:
        context_request = build_context_request(payload)
        schemas.validate("context_request", context_request)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500, detail=f"context_request mapping failed: {exc.message}"
        ) from exc
    result = await runner.run(context_request)
    try:
        response = format_auction_result(result)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        schemas.validate("auction_result", response)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"invalid auction_result: {exc}") from exc
    return response


@app.post("/aip/bid-response", tags=["auction"], status_code=status.HTTP_202_ACCEPTED)
async def submit_bid_response(
    payload: dict[str, Any] = Body(...),
    schemas: SchemaRegistry = Depends(get_schema_service),
    service: BidResponseService = Depends(get_bid_response_service),
) -> dict[str, str]:
    bid_payload = payload.get("bid")
    if not isinstance(bid_payload, dict):
        raise HTTPException(status_code=422, detail="bid payload is required")
    try:
        schemas.validate("bid", bid_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc.message)) from exc
    try:
        await service.submit(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "accepted"}


@app.post("/aip/events", tags=["events"], status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    payload: dict[str, Any] = Body(...),
    event_service: EventService = Depends(get_event_service),
) -> dict[str, Any]:
    try:
        await event_service.ingest(payload)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": "accepted",
        "serve_token": payload.get("serve_token"),
        "event_type": payload.get("event_type"),
    }


def format_auction_result(record: dict[str, Any]) -> dict[str, Any]:
    serve_token = record.get("serve_token") or record.get("record_id")
    auction_id = record.get("auction_id") or record.get("context", {}).get("request_id")
    ttl_source = (
        (record.get("winner") or {}).get("bid", {}).get("ttl_ms")
        or (record.get("winner") or {}).get("ttl_ms")
        or 60000
    )
    ttl_ms = max(int(ttl_source or 60000), 1000)
    response: dict[str, Any] = {
        "auction_id": auction_id,
        "serve_token": serve_token,
        "ttl_ms": ttl_ms,
    }
    if record.get("no_bid"):
        response["no_bid"] = True
        return response
    winner_payload = record.get("winner") or {}
    if not winner_payload:
        response["no_bid"] = True
        return response
    bid_payload = winner_payload.get("bid") or winner_payload
    agent_id = bid_payload.get("agent_id") or winner_payload.get("bidder")
    if not agent_id:
        raise ValueError("winner payload missing agent_id")
    preferred_unit = bid_payload.get("preferred_unit") or "CPX"
    response["winner"] = {
        "agent_id": agent_id,
        "clearing_price_cpx": format_price(record.get("clearing_price", 0.0)),
        "preferred_unit": preferred_unit,
    }
    # Vendor extensions remain inside their `ext.<vendor_id>` namespaces and pass through untouched.
    creative = bid_payload.get("creative") or {}
    render = {
        "label": creative.get("label") or "[Ad]",
        "title": creative.get("title"),
        "body": creative.get("body"),
        "cta": creative.get("cta"),
        "url": creative.get("deeplink") or creative.get("url"),
    }
    response["render"] = {k: v for k, v in render.items() if v is not None}
    return response


def format_price(value: Any) -> str:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    return f"{numeric:.4f}"


def build_context_request(platform_request: dict[str, Any]) -> dict[str, Any]:
    """Map the external PlatformRequest schema to the internal ContextRequest schema used for bidder fanout."""
    context_request: dict[str, Any] = {
        "request_id": platform_request["request_id"],
        "session_id": platform_request["session_id"],
        "platform_id": platform_request["platform_id"],
        "query_text": platform_request["query_text"],
        "locale": platform_request["locale"],
        "geo": platform_request["geo"],
        "ts": platform_request["timestamp"],
        "auth": platform_request["auth"],
    }
    surface = platform_request.get("platform_surface")
    if surface:
        context_request["surface"] = surface
    if platform_request.get("cpx_floor") is not None:
        context_request["pricing"] = {"cpx_floor": format_cpx_floor(platform_request["cpx_floor"])}
    ext_payload = normalize_extensions(platform_request)
    if ext_payload:
        context_request["ext"] = ext_payload
    return context_request


def format_cpx_floor(value: Any) -> str:
    try:
        quantized = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("cpx_floor must be numeric") from exc
    normalized = format(quantized, "f")
    if "." in normalized and len(normalized.split(".")[1]) < 2:
        normalized = f"{normalized}0"
    if "." not in normalized:
        normalized = f"{normalized}.00"
    return normalized


def normalize_extensions(platform_request: dict[str, Any]) -> dict[str, Any]:
    """Preserve vendor-namespaced extensions and attach platform metadata for downstream bidders."""
    ext = platform_request.get("ext")
    ext_payload = deepcopy(ext) if isinstance(ext, dict) else {}
    vendor_id = slug_vendor_id(platform_request.get("platform_id", "platform"))
    platform_metadata: dict[str, Any] = {}
    for key in ("model", "messages", "platform_surface"):
        value = platform_request.get(key)
        if value:
            platform_metadata[key] = value
    if platform_metadata:
        bucket = ext_payload.get(vendor_id)
        if not isinstance(bucket, dict):
            bucket = {}
            ext_payload[vendor_id] = bucket
        existing_meta = bucket.get("platform_request") if isinstance(bucket.get("platform_request"), dict) else {}
        bucket["platform_request"] = {**existing_meta, **platform_metadata}
    return ext_payload


def slug_vendor_id(platform_id: str) -> str:
    if not platform_id:
        return "platform"
    slug = re.sub(r"[^a-z0-9_-]", "-", platform_id.lower())
    slug = slug.strip("-")
    return slug or "platform"
