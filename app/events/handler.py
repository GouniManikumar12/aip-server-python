"""Event ingestion service."""

from __future__ import annotations

from typing import Any

from ..ledger.apply import LedgerService
from .anti_replay import EventReplayGuard
from .validators import validate_event


class EventService:
    def __init__(self, ledger: LedgerService, replay_guard: EventReplayGuard) -> None:
        self._ledger = ledger
        self._guard = replay_guard

    async def ingest(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        validate_event(event_type, payload)
        record_id = payload.get("record_id")
        if not record_id:
            raise ValueError("record_id missing")
        await self._guard.assert_unique(payload.get("event_id"))
        return await self._ledger.record_event(record_id, payload)
