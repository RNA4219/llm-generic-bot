from __future__ import annotations

import random
from typing import Tuple


def jitter_seconds(jitter_range: Tuple[int, int]) -> int:
    lo, hi = jitter_range
    return random.randint(lo, hi)


def next_slot(ts: float, clash: bool, jitter_range: Tuple[int, int] = (60, 180)) -> float:
    if not clash:
        return ts
    return ts + jitter_seconds(jitter_range)


__all__ = ["jitter_seconds", "next_slot"]
