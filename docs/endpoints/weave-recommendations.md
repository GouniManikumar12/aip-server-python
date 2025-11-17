# `/v1/weave/recommendations` Endpoint

## Overview

`POST /v1/weave/recommendations` is the coordination bridge between platform backends and the AIP operator for the **Weave Ad Format** integration. This endpoint implements a cache-first, non-blocking pattern that checks for existing recommendations before triggering new auctions.

Given a `session_id` and `message_id`, it decides whether a Weave recommendation has already been generated for that conversation turn and either returns the cached payload or triggers the full generation pipeline so platforms can continue responding without blocking the LLM.

## Request/Response Specification

### Request Format

**Endpoint:** `POST /v1/weave/recommendations`

**Authentication:** Requires valid API key in headers (implementation-specific)

**Request Body:**
```json
{
  "message_id": "string (required)",
  "session_id": "string (required)",
  "query": "string (optional)"
}
```

**Field Descriptions:**
- `message_id` (required): Unique identifier for this specific message/turn in the conversation
- `session_id` (required): Unique identifier for the conversation session
- `query` (optional): The user's query text, used for auction context

### Response Formats

The endpoint returns one of three response types based on the recommendation state:

#### 1. Completed Response (HTTP 200)
```json
{
  "status": "completed",
  "weave_content": "string (LLM response with embedded [Ad] links)",
  "serve_token": "string (for exposure tracking)",
  "creative_metadata": {
    "brand_name": "string",
    "product_name": "string",
    "description": "string",
    "url": "string"
  }
}
```

#### 2. In Progress Response (HTTP 200)
```json
{
  "status": "in_progress",
  "retry_after_ms": 150,
  "message": "Auction in progress, please retry"
}
```

#### 3. Failed Response (HTTP 200)
```json
{
  "status": "failed",
  "error": "string (error description)"
}
```

### Error Responses

**HTTP 400 - Bad Request:**
```json
{
  "detail": "message_id is required"
}
```
or
```json
{
  "detail": "session_id is required"
}
```

**HTTP 500 - Internal Server Error:**
```json
{
  "detail": "Internal server error: <error message>"
}
```

## Three Response Scenarios

When a platform backend calls the endpoint with `session_id` and `message_id`, the operator checks the internal `recommendations` table. One of three outcomes occurs:

### Scenario 1: Recommendation Already Completed

**When this occurs:**
- A completed record already exists in the `recommendations` table for the given `(session_id, message_id)` pair
- The auction has finished and the Weave creative has been generated

**What the operator does internally:**
1. Query database: `SELECT * FROM recommendations WHERE session_id=? AND message_id=?`
2. Find record with `status: "completed"`
3. Return cached Weave payload immediately

**Response format:**
```json
{
  "status": "completed",
  "weave_content": "[Ad] HubSpot CRM - AI-powered CRM for small teams. Learn more: https://...",
  "serve_token": "stk_abc123",
  "creative_metadata": {
    "brand_name": "HubSpot",
    "product_name": "HubSpot CRM",
    "description": "AI-powered CRM for small teams",
    "url": "https://hubspot.com/crm"
  }
}
```

**What the platform should do next:**
- Immediately weave the `weave_content` into the LLM prompt or response
- No polling or waiting required
- Use `serve_token` for exposure tracking when content is displayed

### Scenario 2: Recommendation In Progress

**When this occurs:**
- A record exists but is marked `status: "in_progress"` because the auction is still running
- The background auction task is actively collecting bids and selecting a winner

**What the operator does internally:**
1. Query database: `SELECT * FROM recommendations WHERE session_id=? AND message_id=?`
2. Find record with `status: "in_progress"`
3. Return retry hint immediately (no blocking)

**Response format:**
```json
{
  "status": "in_progress",
  "retry_after_ms": 150,
  "message": "Auction in progress, please retry"
}
```

**What the platform should do next:**
- Optionally poll 1-2 times with the suggested `retry_after_ms` interval (150ms)
- If still not ready after polling, proceed without Weave content
- Fall back to Citation Format (handled automatically by `aip-ui-sdk`)

### Scenario 3: No Recommendation Exists (Trigger New Auction)

**When this occurs:**
- No record was found for the `(session_id, message_id)` pair
- This is the first request for this conversation turn

**What the operator does internally:**
1. Query database: `SELECT * FROM recommendations WHERE session_id=? AND message_id=?`
2. No record found
3. Create new database entry:
   ```python
   {
     "message_id": request.message_id,
     "session_id": request.session_id,
     "query": request.query,
     "status": "in_progress",
     "created_at": timestamp,
     "updated_at": timestamp
   }
   ```
4. Trigger asynchronous auction flow (background task):
   - Build `context_request` from message/session context
   - Send to brand agents via AIP protocol
   - Collect bids (with timeout, e.g., 500ms)
   - Run auction algorithm to select winner
   - Generate Weave creative (format links with `[Ad]` labels, create `serve_token`)
   - Update database entry with completed payload and `status: "completed"`
5. Return immediately (before auction completes)

**Response format:**
```json
{
  "status": "in_progress",
  "retry_after_ms": 150,
  "message": "Auction initiated, please retry"
}
```

**What the platform should do next:**
- Same as Scenario 2: optionally poll 1-2 times
- If not ready, proceed without Weave content
- Fall back to Citation Format

## Design Principles

### Non-blocking
The endpoint returns immediately and never waits for auction completion. Background tasks handle the auction flow asynchronously, ensuring the platform can proceed with LLM response generation without delay.

### Low-latency Optimized
Designed for conversational AI where <200ms response time is critical. The cache-first pattern ensures instant responses for repeated requests, and the non-blocking design prevents auction delays from affecting user experience.

### Graceful Degradation
If Weave content isn't ready, platforms fall back to Citation Format (handled automatically by `aip-ui-sdk`). Users always see recommendations, just in a different format. No broken experiences.

### Cache-first Pattern
Always check database before triggering new auctions. This prevents duplicate auctions for the same message and ensures instant responses when recommendations are already available.

### Polling-friendly
Returns `retry_after_ms` to enable efficient polling without server overload. Platforms can poll 1-2 times with the suggested interval (150ms) to catch fast auctions without hot-looping.


## Platform Integration Pattern

### Step-by-step Flow

1. **Platform receives user message** and generates `message_id`
   ```python
   message_id = f"msg_{uuid.uuid4()}"
   session_id = current_session.id
   ```

2. **Call `/v1/weave/recommendations`** with `message_id` and `session_id`
   ```python
   response = await http_client.post(
       "https://aip-server.example.com/v1/weave/recommendations",
       json={
           "message_id": message_id,
           "session_id": session_id,
           "query": user_query
       }
   )
   ```

3. **Handle response based on status:**
   - **If `status: 'completed'`**: Weave the returned content into LLM prompt/response
     ```python
     if response["status"] == "completed":
         weave_content = response["weave_content"]
         # Add to LLM prompt or inject into response
         llm_prompt += f"\n\n{weave_content}"
     ```

   - **If `status: 'in_progress'`**: Optionally poll 1-2 times with `retry_after_ms` interval
     ```python
     elif response["status"] == "in_progress":
         retry_after_ms = response.get("retry_after_ms", 150)
         await asyncio.sleep(retry_after_ms / 1000)
         # Retry request (max 1-2 times)
         response = await http_client.post(...)
     ```

   - **If still not ready after polling**: Proceed without Weave content
     ```python
     # Continue with LLM generation
     # aip-ui-sdk will fall back to Citation Format
     ```

4. **LLM generates response** (with or without Weave content embedded)

5. **Return response to user**

6. **aip-ui-sdk automatically renders recommendations** (Weave or Citation Format)

### Timing Considerations

- **Fast auctions (<150ms)**: Single poll will catch completion
- **Medium auctions (150-300ms)**: Two polls will catch completion
- **Slow auctions (>300ms)**: Fall back to Citation Format, no blocking

### Error Handling

```python
try:
    response = await http_client.post("/v1/weave/recommendations", json=payload)
    if response["status"] == "completed":
        # Use Weave content
        pass
    elif response["status"] == "in_progress":
        # Optional: poll once
        pass
    elif response["status"] == "failed":
        # Log error, proceed without Weave
        logger.warning(f"Weave auction failed: {response.get('error')}")
except Exception as e:
    # Network error or server error - proceed without Weave
    logger.error(f"Failed to fetch Weave recommendations: {e}")
    # Continue with LLM generation
```


## Example Code

For complete Python and JavaScript/TypeScript integration examples, see [weave-recommendations-examples.md](./weave-recommendations-examples.md).

## Summary

This endpoint ensures platforms always make the optimal choice: **use Weave if ready, wait briefly if almost ready, or fall back gracefully to Citation Format if not**. This guarantees a seamless user experience regardless of auction timing, while maintaining low latency for conversational AI interactions.

The three-path logic (Completed → In Progress → New) combined with the non-blocking design ensures that:
- Fast auctions (<150ms) are caught with a single poll
- Medium auctions (150-300ms) are caught with two polls
- Slow auctions (>300ms) gracefully fall back to Citation Format
- No auction ever blocks the LLM response generation
- Users always see recommendations, just in different formats based on timing

### Key Metrics to Monitor

- **Cache hit rate**: Percentage of requests returning `status: "completed"` immediately
- **Auction completion time**: Time from auction trigger to completion (p50, p95, p99)
- **Polling frequency**: Average number of polls per message
- **Fallback rate**: Percentage of messages falling back to Citation Format

### Logging Points

The implementation includes logging at key decision points:
- Cache hit (completed recommendation found)
- Cache miss (no recommendation exists, triggering new auction)
- Auction in progress (polling scenario)
- Auction completed successfully
- Auction failed (with error details)

These logs enable monitoring and debugging of the Weave integration flow.
