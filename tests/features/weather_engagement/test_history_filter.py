from __future__ import annotations

from pathlib import Path
from typing import Sequence, cast

import pytest

from llm_generic_bot.features import weather

from ._helpers import _ReactionProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_weather_engagement_ignores_none_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_engagement_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)

    provider = _ReactionProvider(
        (cast(Sequence[int], (None, None)),)
    )

    cfg = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "engagement": {
                "target_reactions": 5,
                "history_limit": 3,
            },
        },
    }

    post = await weather.build_weather_post(
        cfg,
        reaction_history_provider=provider,
        platform="discord",
        channel="general",
        job="weather",
    )

    assert isinstance(post, weather.WeatherPost)
    assert post.engagement_score == pytest.approx(0.0)
