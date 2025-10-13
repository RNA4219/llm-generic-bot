from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, cast

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.weather import WeatherPost


pytestmark = pytest.mark.anyio("asyncio")


HISTORY_SAMPLES: List[Sequence[int]] = []
HISTORY_INVOCATIONS: List[Dict[str, Any]] = []


async def sample_history_provider(
    *,
    job: str,
    limit: int,
    platform: Optional[str],
    channel: Optional[str],
) -> Sequence[int]:
    entry = {
        "job": job,
        "limit": limit,
        "platform": platform,
        "channel": channel,
    }
    HISTORY_INVOCATIONS.append(entry)
    if not HISTORY_SAMPLES:
        return []
    return HISTORY_SAMPLES.pop(0)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_weather_job_uses_engagement_provider(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    global HISTORY_SAMPLES, HISTORY_INVOCATIONS
    HISTORY_SAMPLES = [
        [0, 0, 0],
        [12, 11, 10],
    ]
    HISTORY_INVOCATIONS = []

    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    provider_path = f"{sample_history_provider.__module__}.{sample_history_provider.__name__}"

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        {
            "timezone": "UTC",
            "profiles": {"discord": {"enabled": True, "channel": "weather"}},
            "weather": {
                "schedule": "00:00",
                "engagement": {
                    "history_limit": 3,
                    "history_provider": provider_path,
                },
            },
        },
        queue=queue,
    )
    assert "weather" in jobs

    weather_calls: List[Dict[str, Any]] = []

    async def fake_build_weather_post(
        cfg: Dict[str, Any],
        *,
        reaction_history_provider: Any = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
        job: str = "weather",
        **_: Any,
    ) -> Optional[WeatherPost]:
        weather_calls.append(
            {
                "reaction_history_provider": reaction_history_provider,
                "platform": platform,
                "channel": channel,
                "job": job,
            }
        )
        assert callable(reaction_history_provider)
        engagement_cfg = (
            cfg.get("weather", {}).get("engagement", {}) if isinstance(cfg, dict) else {}
        )
        limit = int(engagement_cfg.get("history_limit", 3))
        history = await reaction_history_provider(
            job=job,
            limit=limit,
            platform=platform,
            channel=channel,
        )
        values = list(history)
        if sum(values) == 0:
            return None
        return WeatherPost("weather-post", engagement_score=0.8)

    monkeypatch.setattr(main_module, "build_weather_post", fake_build_weather_post)

    send_calls: List[Dict[str, Any]] = []

    async def fake_sender_send(
        text: str,
        channel: Optional[str] = None,
        *,
        job: Optional[str] = None,
    ) -> None:
        send_calls.append({"text": text, "channel": channel, "job": job})

    monkeypatch.setattr(orchestrator._sender, "send", fake_sender_send)

    caplog.set_level("INFO")

    first_result = await jobs["weather"]()
    assert first_result is None

    second_result = await jobs["weather"]()
    assert isinstance(second_result, WeatherPost)

    assert all(call["platform"] == "discord" for call in weather_calls)
    assert all(call["channel"] == "weather" for call in weather_calls)
    assert weather_calls[0]["reaction_history_provider"] is weather_calls[1]["reaction_history_provider"]

    last_call = weather_calls[-1]
    await orchestrator.enqueue(
        second_result,
        job=cast(str, last_call["job"]),
        platform=cast(str, last_call["platform"]),
        channel=cast(Optional[str], last_call["channel"]),
    )
    await orchestrator.flush()

    assert HISTORY_INVOCATIONS == [
        {"job": "weather", "limit": 3, "platform": "discord", "channel": "weather"},
        {"job": "weather", "limit": 3, "platform": "discord", "channel": "weather"},
    ]
    assert len(weather_calls) == 2
    assert send_calls == [{"text": "weather-post", "channel": "weather", "job": "weather"}]

    records = [r for r in caplog.records if getattr(r, "event", "") == "send_success"]
    assert len(records) == 1
    assert getattr(records[0], "engagement_score", None) == pytest.approx(0.8)

    await orchestrator.close()
