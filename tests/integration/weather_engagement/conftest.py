from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class _HistoryCall:
    job: str
    limit: int
    platform: Optional[str]
    channel: Optional[str]


class _ReactionHistoryProviderStub:
    def __init__(self, samples: Sequence[Sequence[int]]) -> None:
        self._samples = list(samples)
        self._index = 0
        self.calls: List[_HistoryCall] = []

    async def __call__(
        self,
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> Sequence[int]:
        self.calls.append(
            _HistoryCall(job=job, limit=limit, platform=platform, channel=channel)
        )
        sample = self._samples[self._index]
        if self._index < len(self._samples) - 1:
            self._index += 1
        return sample


@dataclass
class _CooldownStub:
    values: Sequence[float]
    calls: List[Mapping[str, object]]

    def multiplier(
        self,
        platform: str,
        channel: str,
        job: str,
        *,
        time_band_factor: float = 1.0,
        engagement_recent: float = 1.0,
    ) -> float:
        self.calls.append(
            {
                "platform": platform,
                "channel": channel,
                "job": job,
                "time_band_factor": time_band_factor,
                "engagement_recent": engagement_recent,
            }
        )
        return self.values[min(len(self.calls) - 1, len(self.values) - 1)]


class _ReactionProvider:
    def __init__(self, samples: Iterable[Sequence[int]]) -> None:
        self._samples = list(samples)
        self._index = 0

    async def __call__(
        self,
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> Sequence[int]:
        del job, limit, platform, channel
        sample = self._samples[self._index]
        self._index += 1
        return sample


__all__ = [
    "_HistoryCall",
    "_ReactionHistoryProviderStub",
    "_CooldownStub",
    "_ReactionProvider",
    "anyio_backend",
]
