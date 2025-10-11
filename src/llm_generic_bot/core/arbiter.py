import random, time
from typing import Tuple

def jitter_seconds(jitter_range: Tuple[int,int]) -> int:
    lo, hi = jitter_range
    return random.randint(lo, hi)

def next_slot(ts: float, clash: bool, jitter_range=(60,180)) -> float:
    if not clash: return ts
    return ts + jitter_seconds(jitter_range)
