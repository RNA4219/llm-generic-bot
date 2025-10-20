from __future__ import annotations

from pathlib import Path

import pytest

from llm_generic_bot.features import weather

from ._helpers import _CooldownStub, _ReactionProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_weather_engagement_long_term_trend_blends_recent_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)

    cooldown = _CooldownStub(values=[1.0], calls=[])
    provider = _ReactionProvider((([3, 3, 3], [6, 6, 6, 6]),))

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 5,
                "history_limit": 3,
                "long_term_history_limit": 4,
                "long_term_weight": 0.4,
            },
        },
    }

    post = await weather.build_weather_post(
        cfg,
        cooldown=cooldown,  # type: ignore[arg-type]
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert isinstance(post, weather.WeatherPost)
    assert post.engagement_score == pytest.approx(0.76)
    assert post.engagement_recent == pytest.approx(0.6)
    assert post.engagement_long_term == pytest.approx(1.0)
    assert len(cooldown.calls) == 1
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.76)


async def test_weather_engagement_trend_respects_permit_quota_variation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)

    cooldown = _CooldownStub(values=[1.0], calls=[])
    provider = _ReactionProvider((([4, 6], [8, 7, 6, 5]),))

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 10,
                "history_limit": 2,
                "long_term_history_limit": 4,
                "long_term_weight": 0.2,
                "permit_quota_weight": 0.5,
                "permit_quota_ratio": 0.25,
                "min_score": 0.2,
                "resume_score": 0.3,
            },
        },
    }

    post = await weather.build_weather_post(
        cfg,
        cooldown=cooldown,  # type: ignore[arg-type]
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert isinstance(post, weather.WeatherPost)
    assert post.engagement_score == pytest.approx(0.39)
    assert post.engagement_recent == pytest.approx(0.5)
    assert post.engagement_long_term == pytest.approx(0.65)
    assert post.engagement_permit_quota == pytest.approx(0.25)
    assert len(cooldown.calls) == 1
    assert cooldown.calls[0]["engagement_recent"] == pytest.approx(0.39)
