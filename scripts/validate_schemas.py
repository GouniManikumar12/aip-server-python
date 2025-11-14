"""Runs jsonschema validation for all protocol schemas."""

from pathlib import Path
import json
from jsonschema import Draft202012Validator


SCHEMA_DIR = Path(__file__).resolve().parent.parent / "app" / "schemas"


def validate() -> None:
    for schema in SCHEMA_DIR.glob("*.json"):
        data = json.loads(schema.read_text())
        Draft202012Validator.check_schema(data)


if __name__ == "__main__":
    validate()
