"""Schema validation wrappers for event payloads."""

from __future__ import annotations

from ..validation.validator import get_schema_registry


EVENT_SCHEMA_MAP = {
    "cpx_exposure": "event_cpx_exposure",
    "cpc_click": "event_cpc_click",
    "cpa_conversion": "event_cpa_conversion",
    # Backwards compatibility aliases
    "exposure": "event_cpx_exposure",
    "click": "event_cpc_click",
    "conversion": "event_cpa_conversion",
}


def validate_event(event_type: str, payload: dict) -> str:
    schema = EVENT_SCHEMA_MAP.get(event_type)
    if not schema:
        raise ValueError(f"unknown event type {event_type}")
    registry = get_schema_registry()
    registry.validate(schema, payload)
    return schema
