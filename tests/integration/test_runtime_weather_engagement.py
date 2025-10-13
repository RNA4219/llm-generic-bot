from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Sequence

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features import weather as weather_module
from llm_generic_bot.runtime import history as history_module


pytestmark = pytest.mark.anyio("asyncio")


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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_weather_runtime_engagement_controls_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache_path = tmp_path / "weather_cache.json"
    monkeypatch.setattr(weather_module, "CACHE", cache_path)

    async def fake_fetch_current_city(
        city: str,
        *,
        api_key: str,
        units: str,
        lang: str,
    ) -> Dict[str, Any]:
        assert city == "Tokyo"
        return {
            "main": {"temp": 23.0},
            "weather": [{"description": "fine"}],
        }

    monkeypatch.setattr(weather_module, "fetch_current_city", fake_fetch_current_city)

    provider = _ReactionHistoryProviderStub(((0, 0), (8, 7)))
    monkeypatch.setattr(main_module, "REACTION_PROVIDER", provider, raising=False)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {
            "schedule": "00:00",
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "history_provider": "llm_generic_bot.main.REACTION_PROVIDER",
                "history_limit": 2,
                "target_reactions": 5,
                "min_score": 0.5,
                "resume_score": 0.5,
            },
        },
    }

    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    scheduler, orchestrator, _ = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    enqueue_calls: List[Dict[str, Any]] = []
    send_calls: List[Dict[str, Any]] = []

    original_enqueue = orchestrator.enqueue

    async def wrapped_enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        enqueue_calls.append(
            {
                "text": text,
                "job": job,
                "platform": platform,
                "channel": channel,
                "correlation_id": correlation_id,
            }
        )
        return await original_enqueue(
            text,
            job=job,
            platform=platform,
            channel=channel,
            correlation_id=correlation_id,
        )

    async def fake_send(
        text: str,
        channel: Optional[str] = None,
        *,
        job: Optional[str] = None,
    ) -> None:
        send_calls.append(
            {
                "text": text,
                "channel": channel,
                "job": job,
            }
        )

    monkeypatch.setattr(orchestrator, "enqueue", wrapped_enqueue)
    monkeypatch.setattr(orchestrator._sender, "send", fake_send)

    caplog.set_level("INFO", logger="llm_generic_bot.core.orchestrator")

    now = dt.datetime.now(scheduler.tz).replace(hour=0, minute=0, second=0, microsecond=0)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now.timestamp())
    await orchestrator.flush()

    assert enqueue_calls == []
    assert len(provider.calls) == 1
    assert provider.calls[0].job == "weather"
    assert provider.calls[0].platform == "discord"
    assert provider.calls[0].channel == "general"

    records_before = [r for r in caplog.records if r.message == "send_success"]
    assert not records_before

    next_now = now + dt.timedelta(days=1)
    await scheduler._run_due_jobs(next_now)
    await scheduler.dispatch_ready_batches(next_now.timestamp())
    await orchestrator.flush()

    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["text"]
    assert enqueue_calls[0]["job"] == "weather"
    assert enqueue_calls[0]["platform"] == "discord"
    assert enqueue_calls[0]["channel"] == "general"

    assert [call.platform for call in provider.calls] == ["discord", "discord"]
    assert [call.channel for call in provider.calls] == ["general", "general"]

    records = [r for r in caplog.records if r.message == "send_success"]
    assert len(records) == len(records_before) + 1
    assert records[-1].engagement_score == pytest.approx(1.0)

    assert len(send_calls) == 1
    assert send_calls[0]["text"] == enqueue_calls[0]["text"]

    await orchestrator.close()


async def test_setup_runtime_resolves_sample_history_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.example.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    stub = _ReactionHistoryProviderStub(((1, 2, 3),))
    monkeypatch.setattr(history_module, "SAMPLE_REACTION_HISTORY", stub, raising=False)

    history_cfg = (
        settings.get("weather", {}).get("engagement", {}) if isinstance(settings, dict) else {}
    )
    assert (
        history_cfg.get("history_provider")
        == "llm_generic_bot.runtime.history.SAMPLE_REACTION_HISTORY"
    )

    called = False

    async def fake_build_weather_post(
        cfg: Dict[str, Any],
        *,
        reaction_history_provider: weather_module.ReactionHistoryProvider,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
        job: str = "weather",
        cooldown: Optional[Any] = None,
    ) -> Optional[str]:
        nonlocal called
        called = True
        del cfg, cooldown
        assert reaction_history_provider is stub
        history = await reaction_history_provider(
            job=job,
            limit=int(history_cfg.get("history_limit", 1)),
            platform=platform,
            channel=channel,
        )
        assert tuple(history) == (1, 2, 3)
        return None

    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    monkeypatch.setattr(main_module, "build_weather_post", fake_build_weather_post)

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    try:
        await jobs["weather"]()
    finally:
        await orchestrator.close()

    assert called


async def test_runtime_weather_engagement_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "tests.integration.runtime_weather_engagement_provider"
    provider_module = ModuleType(module_name)
    provider_module.PROVIDER = None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, provider_module)

    provider = _ReactionHistoryProviderStub(((0, 0), (8, 7)))
    monkeypatch.setattr(provider_module, "PROVIDER", provider)

    cache_path = tmp_path / "weather_runtime_flow_cache.json"
    monkeypatch.setattr(weather_module, "CACHE", cache_path)

    async def fake_fetch_current_city(
        city: str,
        *,
        api_key: str,
        units: str,
        lang: str,
    ) -> Dict[str, Any]:
        del api_key, units, lang
        assert city == "Tokyo"
        return {
            "main": {"temp": 24.0},
            "weather": [{"description": "clear"}],
        }

    monkeypatch.setattr(weather_module, "fetch_current_city", fake_fetch_current_city)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {
            "schedule": "00:00",
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "history_provider": f"{module_name}.PROVIDER",
                "history_limit": 2,
                "target_reactions": 5,
                "min_score": 0.5,
                "resume_score": 0.5,
            },
        },
    }

    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    job = jobs["weather"]

    first_result = await job()
    assert first_result is None
    assert provider.calls
    assert provider.calls[-1].platform == "discord"
    assert provider.calls[-1].channel == "general"

    second_result = await job()
    assert isinstance(second_result, weather_module.WeatherPost)
    assert second_result.engagement_score == pytest.approx(1.0)

    await orchestrator.close()
