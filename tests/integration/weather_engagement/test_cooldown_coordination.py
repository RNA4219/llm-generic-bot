from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features import weather as weather_module
from llm_generic_bot.runtime import history as history_module

from .conftest import _ReactionHistoryProviderStub

pytestmark = pytest.mark.anyio("asyncio")


async def test_setup_runtime_resolves_sample_history_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_path = Path(__file__).resolve().parents[3] / "config" / "settings.example.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    stub = _ReactionHistoryProviderStub(((1, 2, 3),))
    monkeypatch.setattr(history_module, "SAMPLE_REACTION_HISTORY", stub, raising=False)

    captured: Dict[str, Any] = {}

    async def fake_build_weather_post(
        cfg: Dict[str, Any],
        *,
        reaction_history_provider: weather_module.ReactionHistoryProvider,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
        job: str = "weather",
        cooldown: Optional[Any] = None,
    ) -> Optional[str]:
        captured.update(
            {
                "cfg": cfg,
                "provider": reaction_history_provider,
                "platform": platform,
                "channel": channel,
                "job": job,
                "cooldown": cooldown,
            }
        )
        history_cfg = (
            settings.get("weather", {}).get("engagement", {}) if isinstance(settings, dict) else {}
        )
        assert (
            history_cfg.get("history_provider")
            == "llm_generic_bot.runtime.history.SAMPLE_REACTION_HISTORY"
        )
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

    assert captured["provider"] is stub
    assert captured["platform"] == orchestrator._default_platform
    assert captured["cooldown"] is orchestrator._cooldown
    assert hasattr(captured["cooldown"], "multiplier")
    channel = captured.get("channel") or ""
    multiplier = captured["cooldown"].multiplier(
        platform=captured["platform"],
        channel=channel,
        job=captured["job"],
        time_band_factor=1.0,
        engagement_recent=1.0,
    )
    assert isinstance(multiplier, float)
