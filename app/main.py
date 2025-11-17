from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from uuid import uuid4

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
from .weave import WeaveService


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
    weave_service = WeaveService(
        storage=storage,
        auction_runner=auction_runner,
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
    app.state.weave_service = weave_service
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


def get_weave_service(request: Request) -> WeaveService:
    return request.app.state.weave_service


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
    settings: ServerConfig = Depends(get_server_settings),
) -> dict[str, Any]:
    try:
        schemas.validate("platform_request", payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc.message)) from exc
    try:
        context_request = build_context_request(payload, settings)
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


@app.post("/v1/weave/recommendations", tags=["weave"])
async def get_weave_recommendations(
    payload: dict[str, Any] = Body(...),
    weave_service: WeaveService = Depends(get_weave_service),
) -> dict[str, Any]:
    """
    Coordination bridge for Weave Ad Format integration.

    Implements cache-first, non-blocking pattern:
    - Path 1 (Completed): Returns cached Weave payload immediately
    - Path 2 (In Progress): Returns retry hint while auction runs
    - Path 3 (New): Creates record, triggers background auction, returns retry hint

    Request body:
        {
            "message_id": "msg_123",  # Required
            "session_id": "sess_456", # Required
            "query": "best laptops"   # Optional
        }

    Response scenarios:
        1. Completed: {"status": "completed", "weave_content": "...", "serve_token": "...", ...}
        2. In Progress: {"status": "in_progress", "retry_after_ms": 150, "message": "..."}
        3. Failed: {"status": "failed", "error": "..."}
    """
    # Validate required fields
    message_id = payload.get("message_id")
    session_id = payload.get("session_id")

    if not message_id:
        raise HTTPException(status_code=400, detail="message_id is required")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    query = payload.get("query")

    try:
        # Three-path logic handled by WeaveService:
        # 1. Check cache for completed recommendation
        # 2. Return in_progress if auction running
        # 3. Create new record and trigger background auction
        result = await weave_service.get_or_create_recommendation(
            session_id=session_id,
            message_id=message_id,
            query=query,
        )
        return result
    except Exception as exc:
        # Log error and return 500
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in weave recommendations endpoint: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(exc)}"
        ) from exc


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
    auction_id = record.get("auction_id") or record.get("context", {}).get("context_id")
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
    brand_agent_id = (
        bid_payload.get("brand_agent_id")
        or winner_payload.get("brand_agent_id")
        or winner_payload.get("bidder")
    )
    if not brand_agent_id:
        raise ValueError("winner payload missing brand_agent_id")
    pricing_vector = bid_payload.get("pricing") or {}
    preferred_unit = determine_preferred_unit(bid_payload, pricing_vector)
    reserved_amount = price_for_unit(preferred_unit, pricing_vector)
    if reserved_amount is None:
        raise ValueError("winner pricing missing reserved amount")
    winner_block: dict[str, Any] = {
        "brand_agent_id": brand_agent_id,
        "preferred_unit": preferred_unit,
        "reserved_amount_cents": reserved_amount,
    }
    offer = bid_payload.get("offer") or {}
    creative_input = offer.get("creative_input") if isinstance(offer.get("creative_input"), dict) else {}
    campaign_id = (
        bid_payload.get("campaign_id")
        or offer.get("campaign_id")
        or creative_input.get("campaign_id")
    )
    product_id = (
        bid_payload.get("product_id")
        or offer.get("product_id")
        or creative_input.get("product_id")
    )
    if campaign_id:
        winner_block["campaign_id"] = campaign_id
    if product_id:
        winner_block["product_id"] = product_id
    response["winner"] = winner_block
    # Vendor extensions remain inside their namespaces and pass through untouched.
    descriptions = creative_input.get("descriptions") or []
    value_props = creative_input.get("value_props") or []
    resource_urls = creative_input.get("resource_urls") or []
    render = {
        "label": "[Ad]",
        "title": creative_input.get("product_name") or creative_input.get("brand_name"),
        "body": descriptions[0] if descriptions else None,
        "cta": value_props[0] if value_props else None,
        "url": resource_urls[0] if resource_urls else None,
    }
    response["render"] = {k: v for k, v in render.items() if v is not None}
    return response


def determine_preferred_unit(bid_payload: dict[str, Any], pricing: dict[str, Any]) -> str:
    unit = (bid_payload.get("preferred_unit") or "").upper()
    if unit in {"CPX", "CPC", "CPA"} and price_for_unit(unit, pricing) is not None:
        return unit
    if pricing.get("cpa") is not None:
        return "CPA"
    if pricing.get("cpc") is not None:
        return "CPC"
    return "CPX"


def price_for_unit(unit: str, pricing: dict[str, Any]) -> int | None:
    key = unit.lower()
    return format_price_cents(pricing.get(key))


def format_price_cents(value: Any) -> int | None:
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    try:
        if "." in value_str:
            cents = (Decimal(value_str) * 100).quantize(Decimal("1"))
        else:
            cents = Decimal(value_str)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return int(cents)


def build_context_request(platform_request: dict[str, Any], settings: ServerConfig) -> dict[str, Any]:
    """Map the external PlatformRequest schema to the ContextRequest schema used for bidder fanout."""
    context_id = platform_request.get("request_id") or f"ctx_{uuid4().hex}"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    context_request: dict[str, Any] = {
        "context_id": context_id,
        "session_id": platform_request["session_id"],
        "operator_id": settings.operator.operator_id,
        "platform_id": platform_request["platform_id"],
        "query_text": platform_request["query_text"],
        "locale": platform_request["locale"],
        "geo": platform_request["geo"],
        "timestamp": timestamp,
        "intent": build_intent(platform_request),
        "allowed_formats": list(settings.operator.allowed_formats) or ["weave"],
        "auth": platform_request["auth"],
    }
    verticals = extract_verticals(platform_request)
    if verticals:
        context_request["verticals"] = verticals
    extensions = normalize_extensions(platform_request)
    if extensions:
        context_request["extensions"] = extensions
    return context_request


def extract_verticals(platform_request: dict[str, Any]) -> list[str]:
    features = platform_request.get("features")
    topics: list[str] = []
    if isinstance(features, dict):
        raw_topics = features.get("topic")
        if isinstance(raw_topics, list):
            topics = [topic for topic in raw_topics if isinstance(topic, str)]
    return topics


def build_intent(platform_request: dict[str, Any]) -> dict[str, Any]:
    messages = platform_request.get("messages") or []
    summary = summarize_context(platform_request)
    return {
        "type": infer_intent_type(platform_request),
        "decision_phase": infer_decision_phase(platform_request, messages),
        "context_summary": summary,
        "turn_index": len(messages),
    }


def infer_intent_type(platform_request: dict[str, Any]) -> str:
    try:
        cpx_floor = float(platform_request.get("cpx_floor", 0))
    except (TypeError, ValueError):
        cpx_floor = 0.0
    return "commercial" if cpx_floor > 0 else "informational"


def infer_decision_phase(platform_request: dict[str, Any], messages: list[Any]) -> str:
    length = len(messages)
    if length >= 4:
        return "decide"
    if length == 3:
        return "compare"
    return "research"


def summarize_context(platform_request: dict[str, Any]) -> str:
    query = platform_request.get("query_text", "")
    summary = f"User query: {query}".strip()
    return summary[:280]


def normalize_extensions(platform_request: dict[str, Any]) -> dict[str, Any]:
    """Preserve vendor-namespaced extensions and attach platform metadata for downstream bidders."""
    ext = platform_request.get("ext")
    extensions = deepcopy(ext) if isinstance(ext, dict) else {}
    vendor_id = slug_vendor_id(platform_request.get("platform_id", "platform"))
    platform_metadata: dict[str, Any] = {}
    for key in ("model", "messages", "platform_surface"):
        value = platform_request.get(key)
        if value:
            platform_metadata[key] = value
    if platform_request.get("cpx_floor") is not None:
        platform_metadata["cpx_floor"] = platform_request.get("cpx_floor")
    if platform_metadata:
        bucket = extensions.get(vendor_id)
        if not isinstance(bucket, dict):
            bucket = {}
            extensions[vendor_id] = bucket
        existing_meta = bucket.get("platform_request") if isinstance(bucket.get("platform_request"), dict) else {}
        bucket["platform_request"] = {**existing_meta, **platform_metadata}
    return extensions


def slug_vendor_id(platform_id: str) -> str:
    if not platform_id:
        return "platform"
    slug = re.sub(r"[^a-z0-9_-]", "-", platform_id.lower())
    slug = slug.strip("-")
    return slug or "platform"
