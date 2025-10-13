from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence

import pytest

from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot import main as main_module
from llm_generic_bot.features import weather


pytestmark = pytest.mark.anyio("asyncio")


PROVIDER: Optional["_StubReactionProvider"] = None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class _StubSender:
    sent: List[Mapping[str, object]]

    async def send(self, text: str, channel: Optional[str] = None, *, job: str) -> None:
        self.sent.append({"text": text, "channel": channel, "job": job})


class _StubReactionProvider:
    def __init__(self, samples: Iterable[Sequence[int]]) -> None:
        self._samples = list(samples)
        self._index = 0
        self.calls: List[Mapping[str, object]] = []

    async def __call__(
        self,
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> Sequence[int]:
        call = {
            "job": job,
            "limit": limit,
            "platform": platform,
            "channel": channel,
        }
        self.calls.append(call)
        sample = self._samples[self._index]
        self._index += 1
        return sample


class _StubWeatherBuilder:
    def __init__(self) -> None:
        self.calls: List[Mapping[str, object]] = []
        self.histories: List[Sequence[int]] = []

    async def __call__(
        self,
        cfg: Mapping[str, object],
        *,
        cooldown: object,
        reaction_history_provider: Optional[weather.ReactionHistoryProvider],
        platform: Optional[str],
        channel: Optional[str],
        job: str,
    ) -> Optional[weather.WeatherPost]:
        self.calls.append(
            {
                "cooldown": cooldown,
                "provider": reaction_history_provider,
                "platform": platform,
                "channel": channel,
                "job": job,
            }
        )
        assert reaction_history_provider is not None
        engagement_cfg = dict(cfg.get("weather", {}))
        history_cfg = dict(engagement_cfg.get("engagement", {}))
        limit = int(history_cfg.get("history_limit", 1))
        history = await reaction_history_provider(
            job=job,
            limit=limit,
            platform=platform,
            channel=channel,
        )
        self.histories.append(history)
        if sum(history) < 5:
            return None
        return weather.WeatherPost("SUNNY", engagement_score=0.9)


async def test_runtime_weather_engagement_flow(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    global PROVIDER
    provider = _StubReactionProvider([[0, 0], [6, 7]])
    PROVIDER = provider
    sys.modules.setdefault("tests", types.ModuleType("tests"))
    sys.modules.setdefault("tests.integration", types.ModuleType("tests.integration"))
    sys.modules["tests.integration.test_runtime_weather_engagement"] = sys.modules[__name__]
    builder = _StubWeatherBuilder()
    monkeypatch.setattr(main_module, "build_weather_post", builder)

    settings: Mapping[str, object] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {
            "schedule": "00:00",
            "priority": 3,
            "engagement": {
                "history_provider": "tests.integration.test_runtime_weather_engagement:PROVIDER",
                "history_limit": 3,
            },
        },
    }

    queue = CoalesceQueue(window_seconds=0.0, threshold=2)
    sender = _StubSender(sent=[])

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, sender=sender, queue=queue)

    assert "weather" in jobs

    caplog.set_level("INFO")

    job_weather = jobs["weather"]

    first = await job_weather()

    assert first is None
    assert len(builder.calls) == 1
    assert builder.histories == [[0, 0]]
    assert provider.calls[0] == {
        "job": "weather",
        "limit": 3,
        "platform": "discord",
        "channel": "general",
    }
    assert builder.calls[0]["cooldown"] is orchestrator._cooldown  # type: ignore[attr-defined]

    second = await job_weather()

    assert isinstance(second, weather.WeatherPost)
    assert second.engagement_score == pytest.approx(0.9)
    assert provider.calls[1]["limit"] == 3
    assert builder.histories == [[0, 0], [6, 7]]

    await orchestrator.enqueue(
        second,
        job="weather",
        platform="discord",
        channel="general",
    )
    await orchestrator.flush()

    assert [item["text"] for item in sender.sent] == ["SUNNY"]

    record = next(r for r in caplog.records if getattr(r, "event", "") == "send_success")
    assert record.engagement_score == pytest.approx(0.9)

    await orchestrator.close()
