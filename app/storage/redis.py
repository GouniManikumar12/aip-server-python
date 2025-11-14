"""Redis storage backend using redis-py asyncio client."""

from __future__ import annotations

from typing import Any

import orjson
from redis import asyncio as aioredis


class RedisStorage:
    def __init__(self, *, url: str, prefix: str = "aip:ledger") -> None:
        if not url:
            raise ValueError("redis url missing")
        self._redis = aioredis.from_url(url)
        self._prefix = prefix.rstrip(":")

    def _record_key(self, record_id: str) -> str:
        return f"{self._prefix}:record:{record_id}"

    async def create_record(self, record: dict[str, Any]) -> dict[str, Any]:
        key = self._record_key(record["record_id"])
        await self._redis.set(key, orjson.dumps(record))
        return record

    async def update_record(self, record_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        record = await self.get_record(record_id)
        record.update(updates)
        await self._redis.set(self._record_key(record_id), orjson.dumps(record))
        return record

    async def get_record(self, record_id: str) -> dict[str, Any]:
        raw = await self._redis.get(self._record_key(record_id))
        if raw is None:
            raise KeyError(record_id)
        return orjson.loads(raw)

    async def append_event(self, record_id: str, event: dict[str, Any]) -> dict[str, Any]:
        record = await self.get_record(record_id)
        record.setdefault("events", []).append(event)
        await self._redis.set(self._record_key(record_id), orjson.dumps(record))
        return record

    async def list_records(self) -> list[dict[str, Any]]:
        pattern = self._record_key("*")
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = await self._redis.scan(cursor=cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        if not keys:
            return []
        values = await self._redis.mget(keys)
        return [orjson.loads(value) for value in values if value]
