"""Unit tests for /v1/weave/recommendations endpoint."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.weave.service import WeaveService


@pytest.fixture
def mock_storage():
    """Mock storage backend for testing."""
    storage = AsyncMock()
    storage.get_recommendation = AsyncMock()
    storage.create_recommendation = AsyncMock()
    storage.update_recommendation = AsyncMock()
    return storage


@pytest.fixture
def mock_auction_runner():
    """Mock auction runner for testing."""
    runner = AsyncMock()
    runner.run = AsyncMock()
    return runner


@pytest.fixture
def weave_service(mock_storage, mock_auction_runner):
    """Create WeaveService with mocked dependencies."""
    return WeaveService(
        storage=mock_storage,
        auction_runner=mock_auction_runner,
    )


class TestWeaveRecommendationsEndpoint:
    """Test suite for /v1/weave/recommendations endpoint."""

    def test_missing_message_id(self):
        """Test that missing message_id returns 400."""
        client = TestClient(app)
        response = client.post(
            "/v1/weave/recommendations",
            json={"session_id": "sess_123", "query": "test query"}
        )
        assert response.status_code == 400
        assert "message_id is required" in response.json()["detail"]

    def test_missing_session_id(self):
        """Test that missing session_id returns 400."""
        client = TestClient(app)
        response = client.post(
            "/v1/weave/recommendations",
            json={"message_id": "msg_123", "query": "test query"}
        )
        assert response.status_code == 400
        assert "session_id is required" in response.json()["detail"]


class TestWeaveServiceCompletedPath:
    """Test Path 1: Recommendation already completed."""

    @pytest.mark.asyncio
    async def test_completed_recommendation_returned(self, weave_service, mock_storage):
        """Test that completed recommendation is returned immediately."""
        # Setup: Mock storage returns completed recommendation
        completed_rec = {
            "session_id": "sess_123",
            "message_id": "msg_456",
            "status": "completed",
            "weave_content": "[Ad] Test Product - Great product. Learn more: https://example.com",
            "serve_token": "stk_abc123",
            "creative_metadata": {
                "brand_name": "Test Brand",
                "product_name": "Test Product",
                "description": "Great product",
                "url": "https://example.com"
            }
        }
        mock_storage.get_recommendation.return_value = completed_rec

        # Execute
        result = await weave_service.get_or_create_recommendation(
            session_id="sess_123",
            message_id="msg_456",
            query="test query"
        )

        # Assert
        assert result["status"] == "completed"
        assert result["weave_content"] == completed_rec["weave_content"]
        assert result["serve_token"] == completed_rec["serve_token"]
        assert result["creative_metadata"] == completed_rec["creative_metadata"]

        # Verify storage was queried but no new record created
        mock_storage.get_recommendation.assert_called_once_with("sess_123", "msg_456")
        mock_storage.create_recommendation.assert_not_called()


class TestWeaveServiceInProgressPath:
    """Test Path 2: Recommendation in progress."""

    @pytest.mark.asyncio
    async def test_in_progress_recommendation_returned(self, weave_service, mock_storage):
        """Test that in_progress status is returned with retry hint."""
        # Setup: Mock storage returns in_progress recommendation
        in_progress_rec = {
            "session_id": "sess_123",
            "message_id": "msg_456",
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_storage.get_recommendation.return_value = in_progress_rec

        # Execute
        result = await weave_service.get_or_create_recommendation(
            session_id="sess_123",
            message_id="msg_456",
            query="test query"
        )

        # Assert
        assert result["status"] == "in_progress"
        assert result["retry_after_ms"] == 150
        assert "retry" in result["message"].lower()

        # Verify no new record created
        mock_storage.create_recommendation.assert_not_called()


class TestWeaveServiceNewRecommendationPath:
    """Test Path 3: No recommendation exists, trigger new auction."""

    @pytest.mark.asyncio
    async def test_new_recommendation_triggers_auction(self, weave_service, mock_storage, mock_auction_runner):
        """Test that new recommendation creates record and triggers background auction."""
        # Setup: Mock storage returns None (no existing recommendation)
        mock_storage.get_recommendation.return_value = None
        mock_storage.create_recommendation.return_value = {
            "session_id": "sess_123",
            "message_id": "msg_456",
            "status": "in_progress"
        }

        # Execute
        result = await weave_service.get_or_create_recommendation(
            session_id="sess_123",
            message_id="msg_456",
            query="test query"
        )

        # Assert
        assert result["status"] == "in_progress"
        assert result["retry_after_ms"] == 150

        # Verify new record was created
        mock_storage.create_recommendation.assert_called_once()
        created_rec = mock_storage.create_recommendation.call_args[0][0]
        assert created_rec["session_id"] == "sess_123"
        assert created_rec["message_id"] == "msg_456"
        assert created_rec["status"] == "in_progress"
        assert created_rec["query"] == "test query"

    @pytest.mark.asyncio
    async def test_background_auction_completes_successfully(
        self, weave_service, mock_storage, mock_auction_runner
    ):
        """Test that background auction updates recommendation on success."""
        # Setup: Mock auction result
        auction_result = {
            "serve_token": "stk_xyz789",
            "winner": {
                "offer": {
                    "creative_input": {
                        "brand_name": "Test Brand",
                        "product_name": "Test Product",
                        "descriptions": ["Great product for testing"],
                        "resource_urls": ["https://example.com/product"]
                    }
                }
            }
        }
        mock_auction_runner.run.return_value = auction_result

        # Execute background auction
        await weave_service._run_auction_and_update(
            session_id="sess_123",
            message_id="msg_456",
            query="test query"
        )

        # Assert auction was run
        mock_auction_runner.run.assert_called_once()

        # Assert recommendation was updated with completed status
        mock_storage.update_recommendation.assert_called_once()
        call_args = mock_storage.update_recommendation.call_args
        assert call_args[0][0] == "sess_123"  # session_id
        assert call_args[0][1] == "msg_456"   # message_id

        updates = call_args[0][2]
        assert updates["status"] == "completed"
        assert updates["serve_token"] == "stk_xyz789"
        assert "[Ad]" in updates["weave_content"]
        assert "Test Product" in updates["weave_content"]

    @pytest.mark.asyncio
    async def test_background_auction_handles_failure(
        self, weave_service, mock_storage, mock_auction_runner
    ):
        """Test that background auction updates recommendation on failure."""
        # Setup: Mock auction failure
        mock_auction_runner.run.side_effect = Exception("Auction timeout")

        # Execute background auction
        await weave_service._run_auction_and_update(
            session_id="sess_123",
            message_id="msg_456",
            query="test query"
        )

        # Assert recommendation was updated with failed status
        mock_storage.update_recommendation.assert_called_once()
        call_args = mock_storage.update_recommendation.call_args

        updates = call_args[0][2]
        assert updates["status"] == "failed"
        assert "Auction timeout" in updates["error"]


class TestWeaveServiceFailedPath:
    """Test failed recommendation handling."""

    @pytest.mark.asyncio
    async def test_failed_recommendation_returned(self, weave_service, mock_storage):
        """Test that failed status is returned for failed auctions."""
        # Setup: Mock storage returns failed recommendation
        failed_rec = {
            "session_id": "sess_123",
            "message_id": "msg_456",
            "status": "failed",
            "error": "Auction timeout after 500ms"
        }
        mock_storage.get_recommendation.return_value = failed_rec

        # Execute
        result = await weave_service.get_or_create_recommendation(
            session_id="sess_123",
            message_id="msg_456",
            query="test query"
        )

        # Assert
        assert result["status"] == "failed"
        assert "Auction timeout" in result["error"]


class TestWeaveCreativeGeneration:
    """Test Weave creative generation logic."""

    def test_generate_weave_creative_with_winner(self, weave_service):
        """Test that Weave creative is properly formatted with [Ad] label."""
        auction_result = {
            "serve_token": "stk_test123",
            "winner": {
                "offer": {
                    "creative_input": {
                        "brand_name": "HubSpot",
                        "product_name": "HubSpot CRM",
                        "descriptions": ["AI-powered CRM for small teams"],
                        "resource_urls": ["https://hubspot.com/crm"]
                    }
                }
            }
        }

        creative = weave_service._generate_weave_creative(auction_result)

        assert creative["serve_token"] == "stk_test123"
        assert "[Ad]" in creative["weave_content"]
        assert "HubSpot CRM" in creative["weave_content"]
        assert "AI-powered CRM for small teams" in creative["weave_content"]
        assert "https://hubspot.com/crm" in creative["weave_content"]
        assert creative["creative_metadata"]["brand_name"] == "HubSpot"

    def test_generate_weave_creative_no_winner(self, weave_service):
        """Test that empty Weave is returned when no winner."""
        auction_result = {
            "serve_token": "stk_test123",
            "winner": None
        }

        creative = weave_service._generate_weave_creative(auction_result)

        assert creative["serve_token"] == "stk_test123"
        assert creative["weave_content"] == ""
        assert creative["creative_metadata"] == {}


class TestContextRequestBuilding:
    """Test context_request building logic."""

    def test_build_context_request(self, weave_service):
        """Test that context_request is properly built from session/message context."""
        context_request = weave_service._build_context_request(
            session_id="sess_123",
            message_id="msg_456",
            query="best laptops for developers"
        )

        assert context_request["session_id"] == "sess_123"
        assert "msg_456" in context_request["context_id"]
        assert context_request["query_text"] == "best laptops for developers"
        assert "weave" in context_request["allowed_formats"]
