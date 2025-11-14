"""Stub for generating local bidder/server YAML seeds."""

from pathlib import Path
import yaml


def main() -> None:
    config_dir = Path(__file__).resolve().parent.parent / "app" / "config"
    raise NotImplementedError(f"Write default configs to {config_dir}")


if __name__ == "__main__":
    main()
