"""Category-based distribution using publish/subscribe transports."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from ..transport.canonical_json import canonical_dumps

try:  # pragma: no cover - optional dependency
    from google.cloud import pubsub_v1
except Exception:  # pragma: no cover - fallback when library missing
    pubsub_v1 = None

logger = logging.getLogger(__name__)


class _PublisherProtocol:
    async def publish(self, auction_id: str, pool: str, payload: dict[str, Any]) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


class _LocalPublisher(_PublisherProtocol):
    async def publish(self, auction_id: str, pool: str, payload: dict[str, Any]) -> None:
        logger.info("[local-pubsub] auction=%s pool=%s delivered", auction_id, pool)


class _PubSubPublisher(_PublisherProtocol):
    def __init__(self, options: dict[str, Any]) -> None:
        if pubsub_v1 is None:
            raise RuntimeError("google-cloud-pubsub is required for pubsub backend")
        self._project_id = options.get("project_id")
        if not self._project_id:
            raise ValueError("pubsub backend requires project_id")
        self._topic_prefix = options.get("topic_prefix", "aip-context")
        self._publisher = pubsub_v1.PublisherClient()

    def _topic_path(self, pool: str) -> str:
        topic = f"{self._topic_prefix}-{pool}" if not self._topic_prefix.endswith(pool) else self._topic_prefix
        if topic.startswith("projects/"):
            return topic
        return self._publisher.topic_path(self._project_id, topic)

    async def publish(self, auction_id: str, pool: str, payload: dict[str, Any]) -> None:
        message = canonical_dumps({"auction_id": auction_id, "pool": pool, "context": payload})
        topic = self._topic_path(pool)
        future = self._publisher.publish(topic, message, pool=pool, auction_id=auction_id)
        await asyncio.to_thread(future.result)


class BidFanout:
    def __init__(self, backend: str = "local", options: dict[str, Any] | None = None) -> None:
        options = options or {}
        if backend == "pubsub":
            self._publisher = _PubSubPublisher(options.get("pubsub", {}))
        else:
            self._publisher = _LocalPublisher()

    async def publish(
        self,
        auction_id: str,
        pools: Iterable[str],
        payload: dict[str, Any],
    ) -> None:
        tasks = [self._publisher.publish(auction_id, pool, payload) for pool in set(pools)]
        if tasks:
            await asyncio.gather(*tasks)
