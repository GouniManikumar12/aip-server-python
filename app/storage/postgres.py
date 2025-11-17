"""Postgres storage backend leveraging asyncpg."""

from __future__ import annotations

from typing import Any

import asyncpg
import orjson


class PostgresStorage:
    def __init__(self, *, dsn: str | None = None, **connect_kwargs: Any) -> None:
        if not dsn and not connect_kwargs:
            raise ValueError("postgres connection details missing")
        self._dsn = dsn
        self._connect_kwargs = connect_kwargs
        self._pool: asyncpg.Pool | None = None

    def _encode(self, payload: dict[str, Any]) -> str:
        return orjson.dumps(payload).decode()

    def _decode(self, value: Any) -> dict[str, Any]:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        if isinstance(value, str):
            return orjson.loads(value)
        return value

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self._dsn, **self._connect_kwargs)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ledger_records (
                        record_id TEXT PRIMARY KEY,
                        data JSONB NOT NULL
                    );
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recommendations (
                        session_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        data JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW(),
                        PRIMARY KEY (session_id, message_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_recommendations_status
                    ON recommendations ((data->>'status'));
                    """
                )
        return self._pool

    async def create_record(self, record: dict[str, Any]) -> dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO ledger_records(record_id, data) VALUES($1, $2)""",
                record["record_id"],
                self._encode(record),
            )
        return record

    async def update_record(self, record_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        record = await self.get_record(record_id)
        record.update(updates)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE ledger_records SET data=$2 WHERE record_id=$1""",
                record_id,
                self._encode(record),
            )
        return record

    async def get_record(self, record_id: str) -> dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT data FROM ledger_records WHERE record_id=$1""",
                record_id,
            )
        if not row:
            raise KeyError(record_id)
        return self._decode(row["data"])

    async def append_event(self, record_id: str, event: dict[str, Any]) -> dict[str, Any]:
        record = await self.get_record(record_id)
        record.setdefault("events", []).append(event)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE ledger_records SET data=$2 WHERE record_id=$1""",
                record_id,
                self._encode(record),
            )
        return record

    async def list_records(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT data FROM ledger_records ORDER BY record_id")
        return [self._decode(row["data"]) for row in rows]

    # Recommendation storage methods

    async def get_recommendation(
        self, session_id: str, message_id: str
    ) -> dict[str, Any] | None:
        """Get recommendation by session_id and message_id."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT data FROM recommendations WHERE session_id=$1 AND message_id=$2""",
                session_id,
                message_id,
            )
        if not row:
            return None
        return self._decode(row["data"])

    async def create_recommendation(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        """Create a new recommendation record."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO recommendations(session_id, message_id, data) VALUES($1, $2, $3)""",
                recommendation["session_id"],
                recommendation["message_id"],
                self._encode(recommendation),
            )
        return recommendation

    async def update_recommendation(
        self, session_id: str, message_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an existing recommendation record."""
        recommendation = await self.get_recommendation(session_id, message_id)
        if recommendation is None:
            raise KeyError(f"recommendation ({session_id}, {message_id}) not found")
        recommendation.update(updates)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE recommendations SET data=$3, updated_at=NOW()
                   WHERE session_id=$1 AND message_id=$2""",
                session_id,
                message_id,
                self._encode(recommendation),
            )
        return recommendation
