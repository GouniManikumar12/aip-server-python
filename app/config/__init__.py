"""Configuration helpers for the reference server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

_DEFAULT_SERVER_CONFIG = Path(__file__).resolve().parent / "server.yaml"
_DEFAULT_BIDDER_CONFIG = Path(__file__).resolve().parent / "bidders.yaml"


@dataclass(frozen=True)
class TransportConfig:
    nonce_ttl_seconds: int
    max_clock_skew_ms: int


@dataclass(frozen=True)
class LedgerConfig:
    backend: str
    options: Mapping[str, Any]


@dataclass(frozen=True)
class AuctionConfig:
    window_ms: int
    distribution: Mapping[str, Any]


@dataclass(frozen=True)
class OperatorConfig:
    operator_id: str
    allowed_formats: tuple[str, ...]


@dataclass(frozen=True)
class ServerConfig:
    listen: Mapping[str, Any]
    transport: TransportConfig
    ledger: LedgerConfig
    auction: AuctionConfig
    operator: OperatorConfig


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text()) or {}


@lru_cache(maxsize=1)
def get_server_config() -> ServerConfig:
    path = Path(os.getenv("AIP_CONFIG_PATH", _DEFAULT_SERVER_CONFIG))
    data = _load_yaml(path)
    transport = data.get("transport", {})
    ledger = data.get("ledger", {})
    options = dict(ledger.get("options") or {})
    auction = data.get("auction", {})
    distribution = dict(auction.get("distribution") or {})
    operator = data.get("operator", {})
    allowed_formats = tuple(operator.get("allowed_formats") or ("weave",))
    return ServerConfig(
        listen=data.get("listen", {}),
        transport=TransportConfig(
            nonce_ttl_seconds=int(transport.get("nonce_ttl_seconds", 60)),
            max_clock_skew_ms=int(transport.get("max_clock_skew_ms", 500)),
        ),
        ledger=LedgerConfig(
            backend=str(ledger.get("backend", "in_memory")),
            options=options,
        ),
        auction=AuctionConfig(
            window_ms=int(auction.get("window_ms", data.get("auction_window_ms", 50))),
            distribution=distribution,
        ),
        operator=OperatorConfig(
            operator_id=str(operator.get("id", "operator")),
            allowed_formats=allowed_formats,
        ),
    )


def get_bidder_config_path() -> Path:
    return Path(os.getenv("AIP_BIDDERS_PATH", _DEFAULT_BIDDER_CONFIG))
