from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import MetricsRecorder


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
    def __init__(self, samples: Iterable[Sequence[object]]) -> None:
        self._samples = list(samples)
        self._index = 0

    async def __call__(
        self,
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> Sequence[object]:
        del job, limit, platform, channel
        sample = self._samples[self._index]
        self._index += 1
        return sample


class _SenderStub:
    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send(
        self,
        text: str,
        channel: Optional[str] = None,
        *,
        job: Optional[str] = None,
    ) -> None:
        del channel, job
        self.sent.append(text)


class _CooldownRecorder(CooldownGate):
    def __init__(self) -> None:
        self.recorded: List[tuple[str, Optional[str], str]] = []

    def note_post(self, platform: str, channel: Optional[str], job: str) -> None:  # type: ignore[override]
        self.recorded.append((platform, channel, job))


class _DedupeStub(NearDuplicateFilter):
    def __init__(self) -> None:
        super().__init__(k=5, threshold=0.5)

    def permit(self, text: str) -> bool:  # type: ignore[override]
        del text
        return True


@dataclass
class _MetricsStub(MetricsRecorder):
    increments: MutableMapping[str, list[Mapping[str, str]]]

    def __init__(self) -> None:
        self.increments = {}

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        bucket = self.increments.setdefault(name, [])
        bucket.append(dict(tags or {}))

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        del name, value, tags


ReactionHistoryProvider = _ReactionProvider
CooldownStubType = _CooldownStub


__all__ = [
    "CooldownStubType",
    "ReactionHistoryProvider",
    "_CooldownRecorder",
    "_CooldownStub",
    "_DedupeStub",
    "_MetricsStub",
    "_ReactionProvider",
    "_SenderStub",
]
