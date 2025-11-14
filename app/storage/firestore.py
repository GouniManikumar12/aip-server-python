"""Firestore storage backend leveraging google-cloud-firestore."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from google.cloud import firestore
from google.oauth2 import service_account


class FirestoreStorage:
    def __init__(
        self,
        *,
        project_id: str,
        collection: str = "ledger_records",
        credentials_path: str | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id required for firestore backend")
        client_kwargs: dict[str, Any] = {"project": project_id}
        if credentials_path:
            client_kwargs["credentials"] = service_account.Credentials.from_service_account_file(
                credentials_path
            )
        self._client = firestore.Client(**client_kwargs)
        self._collection_name = collection

    def _collection(self):
        return self._client.collection(self._collection_name)

    async def _run(self, func: Callable, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def create_record(self, record: dict[str, Any]) -> dict[str, Any]:
        await self._run(self._collection().document(record["record_id"]).set, record)
        return record

    async def get_record(self, record_id: str) -> dict[str, Any]:
        doc = await self._run(self._collection().document(record_id).get)
        if not doc.exists:
            raise KeyError(record_id)
        return doc.to_dict()

    async def update_record(self, record_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        record = await self.get_record(record_id)
        record.update(updates)
        await self._run(self._collection().document(record_id).set, record)
        return record

    async def append_event(self, record_id: str, event: dict[str, Any]) -> dict[str, Any]:
        record = await self.get_record(record_id)
        record.setdefault("events", []).append(event)
        await self._run(self._collection().document(record_id).set, record)
        return record

    async def list_records(self) -> list[dict[str, Any]]:
        docs = await self._run(lambda: list(self._collection().stream()))
        return [doc.to_dict() for doc in docs]
