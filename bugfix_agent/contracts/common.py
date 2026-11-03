from __future__ import annotations

from typing import Literal

CONTRACT_SCHEMA_VERSION = "0.1.0"

Confidence = Literal["high", "medium", "low"]

MATCH_POOLS: tuple[str, ...] = ("strict", "locatable_only", "needs_info")
MatchPool = Literal["strict", "locatable_only", "needs_info"]


def is_match_pool(pool: str) -> bool:
    return pool in MATCH_POOLS
