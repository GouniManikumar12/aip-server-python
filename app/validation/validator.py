"""Schema validation helpers wired to the JSON Schema definitions in this repo."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver, ValidationError

EXTENSION_VENDOR_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,63}$"
EXTENSION_DESCRIPTION = (
    "Vendor-namespaced extension container living under ext.<vendor_id>."
)


class SchemaRegistry:
    def __init__(self, schema_dir: Path) -> None:
        self._schema_dir = schema_dir
        self._validators: dict[str, Draft202012Validator] = {}
        self._load()

    def _load(self) -> None:
        for schema_path in sorted(self._schema_dir.glob("*.json")):
            data = json.loads(schema_path.read_text())
            self._inject_extension_namespace(data)
            Draft202012Validator.check_schema(data)
            base_uri = schema_path.resolve().as_uri()
            resolver = RefResolver(base_uri=base_uri, referrer=data)
            self._validators[schema_path.stem] = Draft202012Validator(
                data,
                resolver=resolver,
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            )

    def _inject_extension_namespace(self, schema: Any) -> None:
        """Ensure schemas allow vendor IDs under ext.* without touching core fields."""
        if not isinstance(schema, dict):
            return
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key in ("ext", "extensions"):
                if key in properties:
                    ext_block = properties[key]
                    if isinstance(ext_block, dict) and "$ref" not in ext_block:
                        ext_block.setdefault("description", EXTENSION_DESCRIPTION)
                        ext_block.setdefault("type", "object")
                        ext_block.setdefault(
                            "patternProperties",
                            {
                                EXTENSION_VENDOR_PATTERN: {
                                    "type": "object",
                                    "description": "Operator-owned extension payload.",
                                    "additionalProperties": True,
                                }
                            },
                        )
                        ext_block.setdefault("additionalProperties", False)
        for value in schema.values():
            if isinstance(value, dict):
                self._inject_extension_namespace(value)
            elif isinstance(value, list):
                for item in value:
                    self._inject_extension_namespace(item)

    def validate(self, schema_name: str, payload: Any) -> None:
        try:
            self._validators[schema_name].validate(payload)
        except KeyError as exc:
            raise ValueError(f"unknown schema {schema_name}") from exc


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaRegistry:
    schema_dir = Path(__file__).resolve().parent.parent / "schemas"
    return SchemaRegistry(schema_dir)
