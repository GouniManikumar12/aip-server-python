"""Weave recommendation service for background auction processing."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..auction.runner import AuctionRunner
from ..storage import RecommendationStorage

logger = logging.getLogger(__name__)


@dataclass
class WeaveService:
    """Service for managing Weave recommendations with background auction processing."""

    storage: RecommendationStorage
    auction_runner: AuctionRunner

    async def get_or_create_recommendation(
        self, session_id: str, message_id: str, query: str | None = None
    ) -> dict[str, Any]:
        """
        Get existing recommendation or create new one with background auction.

        Returns one of three states:
        1. Completed: Full weave payload ready
        2. In Progress: Auction running, retry suggested
        3. New: Just created, auction triggered in background
        """
        # Path 1 & 2: Check for existing recommendation
        existing = await self.storage.get_recommendation(session_id, message_id)
        if existing:
            status = existing.get("status")
            if status == "completed":
                # Path 1: Return completed recommendation
                logger.info(
                    f"Cache hit: recommendation completed for {session_id}/{message_id}"
                )
                return {
                    "status": "completed",
                    "weave_content": existing.get("weave_content"),
                    "serve_token": existing.get("serve_token"),
                    "creative_metadata": existing.get("creative_metadata"),
                }
            elif status == "in_progress":
                # Path 2: Auction still running
                logger.info(
                    f"Auction in progress for {session_id}/{message_id}"
                )
                return {
                    "status": "in_progress",
                    "retry_after_ms": 150,
                    "message": "Auction in progress, please retry",
                }
            elif status == "failed":
                # Return failure state
                return {
                    "status": "failed",
                    "error": existing.get("error", "Auction failed"),
                }

        # Path 3: No recommendation exists - create and trigger auction
        logger.info(f"Cache miss: creating new recommendation for {session_id}/{message_id}")
        
        # Create initial record with in_progress status
        recommendation = {
            "session_id": session_id,
            "message_id": message_id,
            "query": query,
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.storage.create_recommendation(recommendation)

        # Trigger background auction (non-blocking)
        asyncio.create_task(
            self._run_auction_and_update(session_id, message_id, query)
        )

        # Return in_progress immediately
        return {
            "status": "in_progress",
            "retry_after_ms": 150,
            "message": "Auction initiated, please retry",
        }

    async def _run_auction_and_update(
        self, session_id: str, message_id: str, query: str | None
    ) -> None:
        """
        Background task: Run auction and update recommendation with results.
        
        This runs asynchronously after the endpoint returns.
        """
        try:
            logger.info(f"Starting background auction for {session_id}/{message_id}")
            
            # Build context_request from session/message context
            context_request = self._build_context_request(
                session_id, message_id, query
            )

            # Run the auction (this handles fanout, bid collection, winner selection)
            auction_result = await self.auction_runner.run(context_request)

            # Generate Weave creative from auction result
            weave_payload = self._generate_weave_creative(auction_result)

            # Update recommendation with completed status
            updates = {
                "status": "completed",
                "weave_content": weave_payload.get("weave_content"),
                "serve_token": weave_payload.get("serve_token"),
                "creative_metadata": weave_payload.get("creative_metadata"),
                "auction_result": auction_result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.storage.update_recommendation(session_id, message_id, updates)
            
            logger.info(
                f"Auction completed successfully for {session_id}/{message_id}, "
                f"serve_token={weave_payload.get('serve_token')}"
            )

        except Exception as exc:
            logger.error(
                f"Auction failed for {session_id}/{message_id}: {exc}",
                exc_info=True,
            )
            # Update with failed status
            updates = {
                "status": "failed",
                "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await self.storage.update_recommendation(session_id, message_id, updates)
            except Exception as update_exc:
                logger.error(f"Failed to update recommendation status: {update_exc}")

    def _build_context_request(
        self, session_id: str, message_id: str, query: str | None
    ) -> dict[str, Any]:
        """Build context_request payload for auction from session/message context."""
        # TODO: This should be enhanced to pull actual conversation context
        # For now, create a minimal context_request
        return {
            "context_id": f"ctx_{message_id}",
            "session_id": session_id,
            "query_text": query or "",
            "allowed_formats": ["weave"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _generate_weave_creative(self, auction_result: dict[str, Any]) -> dict[str, Any]:
        """Generate Weave creative from auction result."""
        # Extract winner and serve_token from auction result
        serve_token = auction_result.get("serve_token")
        winner = auction_result.get("winner")
        
        if not winner:
            # No bid won - return empty weave
            return {
                "weave_content": "",
                "serve_token": serve_token,
                "creative_metadata": {},
            }

        # Extract creative input from winner's offer
        offer = winner.get("offer", {})
        creative_input = offer.get("creative_input", {})
        
        brand_name = creative_input.get("brand_name", "")
        product_name = creative_input.get("product_name", "")
        descriptions = creative_input.get("descriptions", [])
        resource_urls = creative_input.get("resource_urls", [])
        
        # Format as Weave content with [Ad] label
        description = descriptions[0] if descriptions else ""
        url = resource_urls[0] if resource_urls else "#"
        
        weave_content = f"[Ad] {product_name} - {description} Learn more: {url}"
        
        return {
            "weave_content": weave_content,
            "serve_token": serve_token,
            "creative_metadata": {
                "brand_name": brand_name,
                "product_name": product_name,
                "description": description,
                "url": url,
            },
        }

