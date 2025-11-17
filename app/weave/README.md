# Weave Module

This module implements the Weave Ad Format integration for the AIP server.

## Overview

The Weave module provides background auction processing and creative generation for the `/v1/weave/recommendations` endpoint. It implements a cache-first, non-blocking pattern that ensures low-latency responses for conversational AI platforms.

## Components

### WeaveService (`service.py`)

The main service class that orchestrates the Weave recommendation flow.

**Key Methods:**

- `get_or_create_recommendation(session_id, message_id, query)` - Main entry point implementing three-path logic
- `_run_auction_and_update(session_id, message_id, query)` - Background task for auction processing
- `_build_context_request(session_id, message_id, query)` - Builds auction context from message data
- `_generate_weave_creative(auction_result)` - Generates Weave creative with [Ad] labels

## Three-Path Logic

### Path 1: Completed
- Recommendation already exists with `status: "completed"`
- Returns cached Weave payload immediately
- No auction triggered

### Path 2: In Progress
- Recommendation exists with `status: "in_progress"`
- Auction is currently running in background
- Returns retry hint (`retry_after_ms: 150`)

### Path 3: New Recommendation
- No recommendation exists for `(session_id, message_id)` pair
- Creates new record with `status: "in_progress"`
- Triggers background auction using `asyncio.create_task()`
- Returns retry hint immediately

## Background Auction Flow

1. Build `context_request` from session/message context
2. Send to brand agents via AIP protocol (using `AuctionRunner`)
3. Collect bids with timeout (typically 500ms)
4. Run auction algorithm to select winner
5. Generate Weave creative:
   - Format links with `[Ad]` labels
   - Create `serve_token` for tracking
   - Extract creative metadata
6. Update database with completed payload and `status: "completed"`

## Error Handling

- Auction failures are caught and logged
- Failed recommendations are marked with `status: "failed"` and error message
- Platforms can gracefully fall back to Citation Format

## Usage Example

```python
from app.weave import WeaveService

# Initialize service (typically done in app lifespan)
weave_service = WeaveService(
    storage=storage_backend,
    auction_runner=auction_runner
)

# Get or create recommendation
result = await weave_service.get_or_create_recommendation(
    session_id="sess_123",
    message_id="msg_456",
    query="best laptops for developers"
)

if result["status"] == "completed":
    # Use Weave content
    weave_content = result["weave_content"]
    serve_token = result["serve_token"]
elif result["status"] == "in_progress":
    # Optionally poll again after retry_after_ms
    retry_after_ms = result["retry_after_ms"]
elif result["status"] == "failed":
    # Log error and fall back
    error = result["error"]
```

## Logging

The service logs at key decision points:
- Cache hit (completed recommendation found)
- Cache miss (no recommendation exists)
- Auction in progress (polling scenario)
- Auction completed successfully
- Auction failed (with error details)

## Dependencies

- `app.storage.RecommendationStorage` - Storage backend for recommendations
- `app.auction.runner.AuctionRunner` - Auction orchestration
- `asyncio` - Background task management

## Testing

See `tests/unit/test_weave_recommendations.py` for comprehensive test coverage.

## Documentation

- [Endpoint Documentation](../../docs/endpoints/weave-recommendations.md)
- [Integration Examples](../../docs/endpoints/weave-recommendations-examples.md)
- [Implementation Summary](../../docs/endpoints/IMPLEMENTATION_SUMMARY.md)

