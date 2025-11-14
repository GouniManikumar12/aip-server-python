"""Simple stats endpoint exposing ledger counts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..ledger.apply import LedgerService

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_ledger(request: Request) -> LedgerService:
    return request.app.state.ledger


@router.get("/stats")
async def stats(ledger: LedgerService = Depends(_get_ledger)) -> dict[str, int]:
    records = await ledger.list_records()
    return {"records": len(records)}
