from __future__ import annotations

from pathlib import Path

import pytest

from llm_generic_bot.features import weather

from ._helpers import _CooldownStub, _ReactionProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_weather_engagement_resume_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
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

    post_first = await weather.build_weather_post(
        cfg,
        cooldown=cooldown,  # type: ignore[arg-type]
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )
    post_second = await weather.build_weather_post(
        cfg,
        cooldown=cooldown,  # type: ignore[arg-type]
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert post_first is None
    assert isinstance(post_second, weather.WeatherPost)
    assert post_second.engagement_score == pytest.approx(1.0)
    assert len(cooldown.calls) == 2
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.0)
    assert cooldown.calls[0]["time_band_factor"] == pytest.approx(1.2)
    assert cooldown.calls[1]["engagement_recent"] == pytest.approx(1.0)
