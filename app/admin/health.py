"""Admin health endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
