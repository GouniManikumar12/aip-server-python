"""Helpers for canonical JSON serialization used for signing + hashing."""

from __future__ import annotations

from typing import Any, Union

import orjson

_ORJSON_OPTIONS = (
    orjson.OPT_SORT_KEYS
    | orjson.OPT_STRICT_INTEGER
    | orjson.OPT_NAIVE_UTC
    | orjson.OPT_SERIALIZE_NUMPY
)


JsonType = Union[str, int, float, bool, None, list["JsonType"], dict[str, "JsonType"]]


def canonical_dumps(payload: Any) -> bytes:
    """Return canonical JSON bytes with sorted keys and stable formatting."""
    return orjson.dumps(payload, option=_ORJSON_OPTIONS)


def canonical_hash(payload: Any) -> str:
    """Return a SHA-256 hex digest for the canonical JSON representation."""
    import hashlib

    return hashlib.sha256(canonical_dumps(payload)).hexdigest()
