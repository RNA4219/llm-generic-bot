from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import MetricsRecorder, Orchestrator, PermitDecision
from llm_generic_bot.features import weather

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class StubCooldown(CooldownGate):
    def __init__(self) -> None:
        super().__init__(window_sec=60, mult_min=1.0, mult_max=3.0, k_rate=0.1, k_time=0.0, k_eng=0.0)
        self.calls: list[tuple[str, str | None, str]] = []

    def note_post(self, platform: str, channel: str | None, job: str) -> None:  # type: ignore[override]
        self.calls.append((platform, channel, job))


class StubDedupe(NearDuplicateFilter):
    def __init__(self) -> None:
        super().__init__(k=5, threshold=0.5)

    def permit(self, text: str) -> bool:  # type: ignore[override]
        return True


class StubSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    async def send(self, text: str, channel: str | None = None, *, job: str) -> None:
        await asyncio.sleep(0)
        self.sent.append((text, channel))


@dataclass
class MetricsStub(MetricsRecorder):
    increments: list[tuple[str, Mapping[str, str]]]
    observations: list[tuple[str, float, Mapping[str, str]]]

    def __init__(self) -> None:
        self.increments = []
        self.observations = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self.increments.append((name, dict(tags or {})))

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self.observations.append((name, value, dict(tags or {})))


def test_build_weather_post_returns_engagement_metrics() -> None:
    cfg: dict[str, Any] = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Kanto": ["Tokyo"]},
            "thresholds": {},
            "engagement": {"window": 3, "threshold": 2.0},
        },
    }
    reaction_history = [
        {"timestamp": 1700000000, "reactions": 1},
        {"timestamp": 1700001000, "reactions": 5},
    ]

    async def fake_fetch_current_city(*_: Any, **__: Any) -> Mapping[str, Any]:
        return {"main": {"temp": 20.0}, "weather": [{"description": "clear"}]}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(weather, "fetch_current_city", fake_fetch_current_city)

    text, metrics = asyncio.run(
        weather.build_weather_post(
            cfg,
            reaction_history=reaction_history,
            include_metrics=True,
        )
    )
    monkeypatch.undo()

    assert isinstance(text, str)
    assert metrics["recent"] == pytest.approx(3.0)
    assert metrics["threshold"] == pytest.approx(2.0)
    assert metrics["window"] == 3


async def test_low_engagement_suppresses_until_threshold_exceeded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = StubSender()
    cooldown = StubCooldown()
    dedupe = StubDedupe()
    metrics = MetricsStub()

    def permit(_: str, __: str | None, ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        logger=logging.getLogger("test.weather.engagement"),
        platform="discord",
    )

    caplog.set_level(logging.INFO)

    low_metrics = {"recent": 0.2, "threshold": 0.5, "window": 3}
    high_metrics = {"recent": 0.8, "threshold": 0.5, "window": 3}

    await orchestrator.enqueue(
        "first", job="weather", platform="discord", channel="general", engagement=low_metrics
    )
    await orchestrator.enqueue(
        "second", job="weather", platform="discord", channel="general", engagement=high_metrics
    )

    await orchestrator.flush()
    await orchestrator.close()

    assert sender.sent == [("second", "general")]
    assert cooldown.calls == [("discord", "general", "weather")]

    suppressed_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", "") == "send_engagement_suppressed"
    )
    assert suppressed_record.engagement_recent == pytest.approx(low_metrics["recent"])
    assert suppressed_record.engagement_threshold == pytest.approx(low_metrics["threshold"])

    success_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_success"
    )
    assert success_record.engagement_recent == pytest.approx(high_metrics["recent"])
    assert success_record.engagement_threshold == pytest.approx(high_metrics["threshold"])

    success_tags = [tags for name, tags in metrics.increments if name == "send.success"]
    assert success_tags
    assert success_tags[-1]["engagement_state"] == "ok"

    suppressed_tags = [tags for name, tags in metrics.increments if name == "send.suppressed"]
    assert suppressed_tags
    assert suppressed_tags[-1]["engagement_state"] == "low"
