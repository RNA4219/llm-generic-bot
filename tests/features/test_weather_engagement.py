from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import MetricsRecorder, Orchestrator, PermitDecision
from llm_generic_bot.features import weather

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


async def test_weather_engagement_table_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)

    cooldown = _CooldownStub(values=[1.0, 1.5], calls=[])
    histories = [[0, 0], [6, 5]]
    provider = _ReactionProvider(histories)

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 5,
                "history_limit": 3,
                "min_score": 0.4,
                "resume_score": 0.8,
                "time_band_factor": 1.2,
            },
        },
    }

    table = [
        {
            "should_send": False,
            "expected_score": pytest.approx(0.0),
        },
        {
            "should_send": True,
            "expected_score": pytest.approx(1.0),
        },
    ]

    results: List[Optional[str]] = []

    for case in table:
        post = await weather.build_weather_post(
            cfg,
            cooldown=cooldown,  # type: ignore[arg-type]
            reaction_history_provider=provider,
            platform="discord",
            channel="general",
            job="weather",
        )
        results.append(post)

    for result, case in zip(results, table):
        if case["should_send"]:
            assert isinstance(result, weather.WeatherPost)
            assert result.engagement_score == case["expected_score"]
        else:
            assert result is None

    assert len(cooldown.calls) == 2
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.0)
    assert cooldown.calls[0]["time_band_factor"] == pytest.approx(1.2)
    assert cooldown.calls[1]["engagement_recent"] == pytest.approx(1.0)


class _SenderStub:
    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send(self, text: str, channel: Optional[str] = None, *, job: str) -> None:
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


async def test_send_success_log_contains_engagement(caplog: pytest.LogCaptureFixture) -> None:
    sender = _SenderStub()
    cooldown = _CooldownRecorder()
    dedupe = _DedupeStub()
    metrics = _MetricsStub()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision.allow(),
        metrics=metrics,
        platform="discord",
    )

    caplog.set_level("INFO")

    post = weather.WeatherPost("fine", engagement_score=0.6)
    await orchestrator.enqueue(post, job="weather", platform="discord", channel="town-square")
    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == ["fine"]
    record = next(r for r in caplog.records if getattr(r, "event", "") == "send_success")
    assert record.engagement_score == pytest.approx(0.6)

    tags = metrics.increments.get("send.success")
    assert tags is not None and tags[0]["engagement_score"] == "0.6"

    assert cooldown.recorded == [("discord", "town-square", "weather")]
