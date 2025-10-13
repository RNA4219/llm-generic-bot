from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features import weather as weather_module


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

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    enqueue_calls: List[Dict[str, Any]] = []

    async def fake_enqueue(
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
        return "corr"

    monkeypatch.setattr(orchestrator, "enqueue", fake_enqueue)

    job = jobs["weather"]

    result_low = await job()
    assert result_low is None

    await scheduler.dispatch_ready_batches()
    assert enqueue_calls == []

    now = dt.datetime.now(scheduler.tz).replace(hour=0, minute=0, second=0, microsecond=0)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now.timestamp())

    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["text"]
    assert enqueue_calls[0]["job"] == "weather"
    assert enqueue_calls[0]["platform"] == "discord"
    assert enqueue_calls[0]["channel"] == "general"

    assert [call.platform for call in provider.calls] == ["discord", "discord"]
    assert [call.channel for call in provider.calls] == ["general", "general"]

    await orchestrator.close()
