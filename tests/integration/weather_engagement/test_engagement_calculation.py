from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features import weather as weather_module

from .conftest import _ReactionHistoryProviderStub

pytestmark = pytest.mark.anyio("asyncio")


async def test_runtime_weather_engagement_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "tests.integration.weather_engagement.runtime_weather_engagement_provider"
    provider_module = ModuleType(module_name)
    provider_module.PROVIDER = None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, provider_module)

    provider = _ReactionHistoryProviderStub(((0, 0), (8, 7)))
    monkeypatch.setattr(provider_module, "PROVIDER", provider)

    cache_path = tmp_path / "weather_runtime_flow_cache.json"
    monkeypatch.setattr(weather_module.cache, "DEFAULT_CACHE_PATH", cache_path)
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

    monkeypatch.setattr(
        weather_module.post_builder,
        "fetch_current_city",
        fake_fetch_current_city,
    )

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
