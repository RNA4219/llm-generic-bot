from __future__ import annotations

import asyncio
import logging
from collections import deque
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pytest

from llm_generic_bot.core.orchestrator import MetricsRecorder, Orchestrator, PermitDecision
from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.features.weather import WeatherPostResult, build_weather_post


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class CooldownStub(CooldownGate):
    def __init__(self, multipliers: list[float]) -> None:
        # window値だけ親の初期化を行う
        super().__init__(window_sec=1800, mult_min=1.0, mult_max=6.0, k_rate=0.0, k_time=0.0, k_eng=0.0)
        self._multipliers = deque(multipliers)
        self.calls: list[Dict[str, Any]] = []

    def multiplier(  # type: ignore[override]
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
        value = self._multipliers[0] if self._multipliers else 1.0
        if len(self._multipliers) > 1:
            self._multipliers.popleft()
        return value


class _StubDedupe(NearDuplicateFilter):
    def __init__(self) -> None:
        super().__init__(k=5, threshold=0.5)

    def permit(self, text: str) -> bool:  # type: ignore[override]
        return True


class _StubSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Optional[str]]] = []

    async def send(self, text: str, channel: Optional[str] = None, *, job: str) -> None:
        await asyncio.sleep(0)
        self.sent.append((text, channel))


class _MetricsProbe(MetricsRecorder):
    def __init__(self) -> None:
        self.records: list[tuple[str, Mapping[str, str] | None]] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self.records.append((name, dict(tags) if tags is not None else None))

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self.records.append((name, dict(tags) if tags is not None else None))


async def _fake_fetch_current_city(
    city: str,
    *,
    api_key: str,
    units: str,
    lang: str,
) -> Dict[str, Any]:
    return {"main": {"temp": 25.0}, "weather": [{"description": "sunny"}]}


@pytest.fixture
def base_cfg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Dict[str, Any]:
    from llm_generic_bot.features import weather

    cache_path = tmp_path / "weather_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)
    monkeypatch.setattr(weather, "fetch_current_city", _fake_fetch_current_city)
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy")
    return {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Kanto": ["Tokyo"]},
            "thresholds": {},
            "template": {
                "header": "header",
                "line": "{city}: {temp:.1f}℃",
                "footer_warn": "warn\n{bullets}",
            },
            "cooldown": {"suppress_threshold": 1.5},
        },
    }


async def test_weather_post_suppressed_when_low_engagement(base_cfg: Dict[str, Any]) -> None:
    cooldown = CooldownStub([2.0])

    async def provider(_: str, __: Optional[str], ___: str) -> float:
        return 0.2

    result = await build_weather_post(
        base_cfg,
        cooldown=cooldown,
        platform="discord",
        channel="general",
        job="weather",
        engagement_provider=provider,
    )

    assert result is None
    assert cooldown.calls
    assert pytest.approx(cooldown.calls[0]["engagement_recent"], rel=1e-6) == 0.2


async def test_weather_post_resumes_when_threshold_recovers(base_cfg: Dict[str, Any]) -> None:
    cooldown = CooldownStub([2.0, 1.0])

    async def provider(_: str, __: Optional[str], ___: str) -> float:
        return 0.2 if not cooldown.calls else 0.9

    first = await build_weather_post(
        base_cfg,
        cooldown=cooldown,
        platform="discord",
        channel="general",
        job="weather",
        engagement_provider=provider,
    )
    assert first is None

    second = await build_weather_post(
        base_cfg,
        cooldown=cooldown,
        platform="discord",
        channel="general",
        job="weather",
        engagement_provider=provider,
    )

    assert isinstance(second, WeatherPostResult)
    assert "Tokyo" in second.text
    assert pytest.approx(second.engagement_score, rel=1e-6) == 0.9


async def test_send_success_logs_include_engagement_score(caplog: pytest.LogCaptureFixture) -> None:
    sender = _StubSender()
    cooldown = CooldownStub([1.0])
    dedupe = _StubDedupe()
    metrics = _MetricsProbe()

    def permit(_: str, __: Optional[str], ___: str) -> PermitDecision:
        return PermitDecision.allow()

    orchestrator = Orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics,
        logger=logging.getLogger("test.weather"),
        platform="discord",
    )

    caplog.set_level(logging.INFO)
    await orchestrator.enqueue(
        "text",
        job="weather",
        platform="discord",
        channel="general",
        metadata={"engagement_score": 0.42},
    )
    await orchestrator.flush()
    await orchestrator.close()

    success_record = next(
        record for record in caplog.records if getattr(record, "event", "") == "send_success"
    )
    assert pytest.approx(getattr(success_record, "engagement_score"), rel=1e-6) == 0.42

    send_success_tags = [tags for name, tags in metrics.records if name == "send.success"]
    assert send_success_tags
    assert send_success_tags[0] is not None
    assert send_success_tags[0]["engagement_score"] == "0.42"

