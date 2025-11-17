"""Storage backend factory."""

from __future__ import annotations

from typing import Protocol

from ..config import ServerConfig
from .in_memory import InMemoryStorage
from .postgres import PostgresStorage
from .redis import RedisStorage
from .firestore import FirestoreStorage


class LedgerStorage(Protocol):
    async def create_record(self, record: dict) -> dict: ...

    async def update_record(self, record_id: str, updates: dict) -> dict: ...

    async def get_record(self, record_id: str) -> dict: ...

    async def append_event(self, record_id: str, event: dict) -> dict: ...

    async def list_records(self) -> list[dict]: ...


class RecommendationStorage(Protocol):
    """Storage protocol for Weave recommendations."""

    async def get_recommendation(
        self, session_id: str, message_id: str
    ) -> dict | None:
        """Get recommendation by session_id and message_id. Returns None if not found."""
        ...

    async def create_recommendation(self, recommendation: dict) -> dict:
        """Create a new recommendation record."""
        ...

    async def update_recommendation(
        self, session_id: str, message_id: str, updates: dict
    ) -> dict:
        """Update an existing recommendation record."""
        ...


def build_storage(config: ServerConfig) -> LedgerStorage:
    backend = config.ledger.backend
    options = dict(config.ledger.options)
    if backend == "in_memory":
        return InMemoryStorage()
    if backend == "redis":
        return RedisStorage(**options)
    if backend == "postgres":
        return PostgresStorage(**options)
    if backend == "firestore":
        return FirestoreStorage(**options)
    raise ValueError(f"unknown storage backend {backend}")
