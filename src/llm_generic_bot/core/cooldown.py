from __future__ import annotations
import time, math
from collections import deque
from typing import Dict, Tuple, Deque

class CooldownGate:
    def __init__(self, window_sec: int, mult_min: float, mult_max: float,
                 k_rate: float, k_time: float, k_eng: float):
        self.window = window_sec
        self.mult_min = mult_min
        self.mult_max = mult_max
        self.k_rate = k_rate
        self.k_time = k_time
        self.k_eng = k_eng
        self.history: Dict[Tuple[str,str,str], Deque[float]] = {}

    def _key(self, platform: str, channel: str, job: str) -> Tuple[str,str,str]:
        return (platform or "-", channel or "-", job or "-")

    def note_post(self, platform: str, channel: str, job: str) -> None:
        key = self._key(platform, channel, job)
        q = self.history.setdefault(key, deque())
        now = time.time()
        q.append(now)
        # evict old
        cut = now - self.window
        while q and q[0] < cut:
            q.popleft()

    def multiplier(self, platform: str, channel: str, job: str,
                   time_band_factor: float = 1.0, engagement_recent: float = 1.0) -> float:
        key = self._key(platform, channel, job)
        q = self.history.get(key)
        if q is not None:
            now = time.time()
            cut = now - self.window
            while q and q[0] < cut:
                q.popleft()
            rate = len(q)
        else:
            rate = 0
        mult = 1.0 + self.k_rate*rate + self.k_time*time_band_factor + self.k_eng*(1.0 - engagement_recent)
        return max(self.mult_min, min(self.mult_max, mult))
