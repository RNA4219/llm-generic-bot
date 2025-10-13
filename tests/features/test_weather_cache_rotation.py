from __future__ import annotations

import json
import asyncio
from collections import deque
from pathlib import Path
from typing import Any, Dict

import pytest

from llm_generic_bot.features import weather


def test_weather_cache_rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "weather_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy")

    temps = deque([20.0, 26.0])

    async def fake_fetch_current_city(
        city: str,
        *,
        api_key: str,
        units: str,
        lang: str,
    ) -> Dict[str, Any]:
        temp = temps.popleft()
        return {"main": {"temp": temp}, "weather": [{"description": "clear"}]}

    monkeypatch.setattr(weather, "fetch_current_city", fake_fetch_current_city)

    cfg: Dict[str, Any] = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "thresholds": {"delta_warn": 1.0, "delta_strong": 5.0},
            "template": {
                "header": "header",
                "line": "{city}: {temp:.1f}℃ {delta_tag}",
                "footer_warn": "warn\n{bullets}",
            },
        },
    }

    asyncio.run(weather.build_weather_post(cfg))
    first_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert first_cache["today"]["Tokyo"]["temp"] == 20.0
    assert first_cache["yesterday"] == {}

    output_second = asyncio.run(weather.build_weather_post(cfg))
    second_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert second_cache["yesterday"]["Tokyo"]["temp"] == 20.0
    assert second_cache["today"]["Tokyo"]["temp"] == 26.0
    assert "(+6.0)" in output_second


def test_weather_cache_rotation_falls_back_to_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "weather_cache.json"
    monkeypatch.setattr(weather, "CACHE", cache_path)
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy")

    temps = deque([20.0])

    async def fake_fetch_current_city(
        city: str,
        *,
        api_key: str,
        units: str,
        lang: str,
    ) -> Dict[str, Any]:
        if temps:
            temp = temps.popleft()
            return {"main": {"temp": temp}, "weather": [{"description": "clear"}]}
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(weather, "fetch_current_city", fake_fetch_current_city)

    cfg: Dict[str, Any] = {
        "openweather": {"units": "metric", "lang": "ja"},
        "weather": {
            "cities": {"Test": ["Tokyo"]},
            "thresholds": {"delta_warn": 1.0, "delta_strong": 5.0},
            "template": {
                "header": "header",
                "line": "{city}: {temp:.1f}℃ {delta_tag}",
                "footer_warn": "warn\n{bullets}",
            },
        },
    }

    asyncio.run(weather.build_weather_post(cfg))
    first_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert first_cache["today"]["Tokyo"]["temp"] == 20.0

    output_error = asyncio.run(weather.build_weather_post(cfg))
    second_cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert "Tokyo: 20.0℃" in output_error
    assert second_cache["today"]["Tokyo"]["temp"] == 20.0
    assert second_cache["yesterday"]["Tokyo"]["temp"] == 20.0
