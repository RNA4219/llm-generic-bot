from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features import weather as weather_module

from .conftest import _ReactionHistoryProviderStub

pytestmark = pytest.mark.anyio("asyncio")


async def test_weather_runtime_engagement_controls_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache_path = tmp_path / "weather_cache.json"
    monkeypatch.setattr(weather_module.cache, "DEFAULT_CACHE_PATH", cache_path)
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

    monkeypatch.setattr(
        weather_module.post_builder,
        "fetch_current_city",
        fake_fetch_current_city,
    )

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
    last_record = records[-1]
    assert getattr(last_record, "engagement_score") == pytest.approx(1.0)

    assert len(send_calls) == 1
    assert send_calls[0]["text"] == enqueue_calls[0]["text"]

    await orchestrator.close()
