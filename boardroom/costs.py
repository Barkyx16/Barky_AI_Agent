"""Estimated API cost per meeting, from the token usage the API reports."""

from __future__ import annotations

import os
from dataclasses import dataclass

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "web_searches")


@dataclass(frozen=True)
class Prices:
    """USD per million tokens, and per web search. Defaults are Claude Opus 5.5 list prices."""

    input: float = 4.00
    output: float = 20.00
    cache_write: float = 5.00
    cache_read: float = 0.20
    search: float = 0.01

    @classmethod
    def from_env(cls) -> "Prices":
        def num(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, default))
            except ValueError:
                return default

        return cls(
            input=num("BOARDROOM_PRICE_INPUT", cls.input),
            output=num("BOARDROOM_PRICE_OUTPUT", cls.output),
            cache_write=num("BOARDROOM_PRICE_CACHE_WRITE", cls.cache_write),
            cache_read=num("BOARDROOM_PRICE_CACHE_READ", cls.cache_read),
            search=num("BOARDROOM_PRICE_SEARCH", cls.search),
        )

    def cost(self, usage: dict) -> float:
        return (
            usage.get("input_tokens", 0) * self.input
            + usage.get("output_tokens", 0) * self.output
            + usage.get("cache_write_tokens", 0) * self.cache_write
            + usage.get("cache_read_tokens", 0) * self.cache_read
        ) / 1_000_000 + usage.get("web_searches", 0) * self.search


def add_usage(total: dict, usage: dict) -> None:
    for key in USAGE_KEYS:
        total[key] = total.get(key, 0) + int(usage.get(key, 0) or 0)
