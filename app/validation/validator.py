"""Schema validation helpers wired to the JSON Schema definitions in this repo."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import json
from jsonschema import Draft202012Validator, ValidationError


class SchemaRegistry:
    def __init__(self, schema_dir: Path) -> None:
        self._schema_dir = schema_dir
        self._validators: dict[str, Draft202012Validator] = {}
        self._load()

    def _load(self) -> None:
        for schema_path in self._schema_dir.glob("*.json"):
            data = json.loads(schema_path.read_text())
            Draft202012Validator.check_schema(data)
            self._validators[schema_path.stem] = Draft202012Validator(data)

    def validate(self, schema_name: str, payload: Any) -> None:
        try:
            self._validators[schema_name].validate(payload)
        except KeyError as exc:
            raise ValueError(f"unknown schema {schema_name}") from exc


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaRegistry:
    schema_dir = Path(__file__).resolve().parent.parent / "schemas"
    return SchemaRegistry(schema_dir)
