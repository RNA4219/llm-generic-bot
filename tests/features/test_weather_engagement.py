from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence, cast

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import (
    MetricsRecorder,
    Orchestrator,
    PermitDecision,
    PermitEvaluator,
)
from llm_generic_bot.features import weather
from llm_generic_bot.features.weather import cache as weather_cache
from llm_generic_bot.features.weather import engagement as weather_engagement
from llm_generic_bot.features.weather import post_builder as weather_post_builder

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


async def test_weather_engagement_table_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather_cache, "DEFAULT_CACHE_PATH", cache_path)
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
            assert isinstance(result, weather_post_builder.WeatherPost)
            assert result.engagement_score == case["expected_score"]
        else:
            assert result is None

    assert len(cooldown.calls) == 2
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.0)
    assert cooldown.calls[0]["time_band_factor"] == pytest.approx(1.2)
    assert cooldown.calls[1]["engagement_recent"] == pytest.approx(1.0)


async def test_weather_engagement_ignores_none_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather_cache, "DEFAULT_CACHE_PATH", cache_path)
    monkeypatch.setattr(weather, "CACHE", cache_path)

    provider = _ReactionProvider(
        (cast(Sequence[int], (None, None)),)
    )

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 5,
                "history_limit": 3,
            },
        },
    }

    post = await weather.build_weather_post(
        cfg,
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert isinstance(post, weather_post_builder.WeatherPost)
    assert post.engagement_score == pytest.approx(0.0)


async def test_weather_engagement_long_term_trend_blends_recent_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather_cache, "DEFAULT_CACHE_PATH", cache_path)
    monkeypatch.setattr(weather, "CACHE", cache_path)

    cooldown = _CooldownStub(values=[1.0], calls=[])
    provider = _ReactionProvider((([3, 3, 3], [6, 6, 6, 6]),))

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 5,
                "history_limit": 3,
                "long_term_history_limit": 4,
                "long_term_weight": 0.4,
            },
        },
    }

    post = await weather.build_weather_post(
        cfg,
        cooldown=cooldown,  # type: ignore[arg-type]
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert isinstance(post, weather_post_builder.WeatherPost)
    assert post.engagement_score == pytest.approx(0.76)
    assert post.engagement_recent == pytest.approx(0.6)
    assert post.engagement_long_term == pytest.approx(1.0)
    assert len(cooldown.calls) == 1
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.76)


async def test_weather_engagement_trend_respects_permit_quota_variation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather_cache, "DEFAULT_CACHE_PATH", cache_path)
    monkeypatch.setattr(weather, "CACHE", cache_path)

    cooldown = _CooldownStub(values=[1.0], calls=[])
    provider = _ReactionProvider((([4, 6], [8, 7, 6, 5]),))

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 10,
                "history_limit": 2,
                "long_term_history_limit": 4,
                "long_term_weight": 0.2,
                "permit_quota_weight": 0.5,
                "permit_quota_ratio": 0.25,
                "min_score": 0.2,
                "resume_score": 0.3,
            },
        },
    }

    post = await weather.build_weather_post(
        cfg,
        cooldown=cooldown,  # type: ignore[arg-type]
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert isinstance(post, weather_post_builder.WeatherPost)
    assert post.engagement_score == pytest.approx(0.39)
    assert post.engagement_recent == pytest.approx(0.5)
    assert post.engagement_long_term == pytest.approx(0.65)
    assert post.engagement_permit_quota == pytest.approx(0.25)
    assert len(cooldown.calls) == 1
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.39)


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


async def test_send_success_log_contains_engagement(caplog: pytest.LogCaptureFixture) -> None:
    sender = _SenderStub()
    cooldown = _CooldownRecorder()
    dedupe = _DedupeStub()
    metrics = _MetricsStub()

    def _permit(_: str, __: Optional[str], ___: str) -> PermitDecision:
        return PermitDecision.allow()

    permit_fn = cast(PermitEvaluator, _permit)

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit_fn,
        metrics=metrics,
        platform="discord",
    )

    caplog.set_level("INFO")

    post = weather_post_builder.WeatherPost("fine", engagement_score=0.6)
    await orchestrator.enqueue(post, job="weather", platform="discord", channel="town-square")
    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == ["fine"]
    record = next(r for r in caplog.records if getattr(r, "event", "") == "send_success")
    engagement_value = getattr(record, "engagement_score", None)
    assert isinstance(engagement_value, float)
    assert engagement_value == pytest.approx(0.6)

    tags = metrics.increments.get("send.success")
    assert tags is not None and tags[0]["engagement_score"] == "0.6"

    assert cooldown.recorded == [("discord", "town-square", "weather")]
