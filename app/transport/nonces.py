"""Simple nonce cache used for anti-replay enforcement."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque


class NonceError(ValueError):
    """Raised when a nonce is missing or reused."""


@dataclass
class _NonceEntry:
    value: str
    expires_at: datetime


class NonceCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._entries: Deque[_NonceEntry] = deque()
        self._known: set[str] = set()
        self._lock = asyncio.Lock()

    async def assert_fresh(self, nonce: str) -> None:
        if not nonce:
            raise NonceError("nonce missing")
        async with self._lock:
            self._evict_expired()
            if nonce in self._known:
                raise NonceError("nonce already seen")
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl)
            self._entries.append(_NonceEntry(nonce, expires_at))
            self._known.add(nonce)

    def _evict_expired(self) -> None:
        now = datetime.now(timezone.utc)
        while self._entries and self._entries[0].expires_at <= now:
            expired = self._entries.popleft()
            self._known.discard(expired.value)
