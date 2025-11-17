"""In-memory storage backend for ledger records and recommendations."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any


class InMemoryStorage:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._recommendations: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create_record(self, record: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._records[record["record_id"]] = deepcopy(record)
            return deepcopy(record)

    async def update_record(self, record_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if record_id not in self._records:
                raise KeyError(record_id)
            self._records[record_id].update(updates)
            return deepcopy(self._records[record_id])

    async def get_record(self, record_id: str) -> dict[str, Any]:
        async with self._lock:
            try:
                return deepcopy(self._records[record_id])
            except KeyError as exc:
                raise KeyError(f"record {record_id} not found") from exc

    async def append_event(self, record_id: str, event: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if record_id not in self._records:
                raise KeyError(record_id)
            self._records[record_id].setdefault("events", []).append(deepcopy(event))
            return deepcopy(self._records[record_id])

    async def list_records(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [deepcopy(record) for record in self._records.values()]

    # Recommendation storage methods

    async def get_recommendation(
        self, session_id: str, message_id: str
    ) -> dict[str, Any] | None:
        """Get recommendation by session_id and message_id."""
        async with self._lock:
            key = (session_id, message_id)
            rec = self._recommendations.get(key)
            return deepcopy(rec) if rec else None

    async def create_recommendation(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        """Create a new recommendation record."""
        async with self._lock:
            key = (recommendation["session_id"], recommendation["message_id"])
            self._recommendations[key] = deepcopy(recommendation)
            return deepcopy(recommendation)

    async def update_recommendation(
        self, session_id: str, message_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an existing recommendation record."""
        async with self._lock:
            key = (session_id, message_id)
            if key not in self._recommendations:
                raise KeyError(f"recommendation ({session_id}, {message_id}) not found")
            self._recommendations[key].update(updates)
            return deepcopy(self._recommendations[key])
