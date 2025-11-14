"""Bidder registry backed by YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class BidderConfig:
    name: str
    endpoint: str
    public_key: str
    timeout_ms: int = 200
    pools: tuple[str, ...] = ("default",)

    def is_subscribed(self, pools: Iterable[str]) -> bool:
        pool_set = set(pools)
        return any(pool in pool_set for pool in self.pools)


class BidderRegistry:
    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._bidders: dict[str, BidderConfig] = {}
        self.reload()

    def reload(self) -> None:
        data = yaml.safe_load(self._path.read_text()) or {}
        bidders = {}
        for item in data.get("bidders", []):
            cfg = BidderConfig(
                name=item["name"],
                endpoint=item["endpoint"],
                public_key=item.get("public_key", ""),
                timeout_ms=int(item.get("timeout_ms", 200)),
                pools=tuple(item.get("pools", ["default"])),
            )
            bidders[cfg.name] = cfg
        self._bidders = bidders

    def all(self) -> Iterable[BidderConfig]:
        return self._bidders.values()

    def get(self, name: str) -> BidderConfig | None:
        return self._bidders.get(name)

    def filter_by_pools(self, pools: Iterable[str]) -> list[BidderConfig]:
        return [bidder for bidder in self._bidders.values() if bidder.is_subscribed(pools)]
