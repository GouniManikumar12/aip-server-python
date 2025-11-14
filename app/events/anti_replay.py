"""Simple event replay guard based on event_id uniqueness."""

from __future__ import annotations

import asyncio


class EventReplayGuard:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()

    async def assert_unique(self, event_id: str) -> None:
        if not event_id:
            raise ValueError("event_id missing")
        async with self._lock:
            if event_id in self._seen:
                raise ValueError("event already ingested")
            self._seen.add(event_id)
