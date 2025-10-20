from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, TypeAlias

from ..core.cooldown import CooldownGate
from .weather.post_builder import (
    ReactionHistoryProvider as _ReactionHistoryProvider,
    WeatherPost as _WeatherPost,
)

ReactionHistoryProvider: TypeAlias = type[_ReactionHistoryProvider]
WeatherPost: TypeAlias = type[_WeatherPost]
CACHE: Path

async def build_weather_post(
    cfg: Mapping[str, object],
    *,
    cooldown: Optional[CooldownGate] = ...,
    reaction_history_provider: Optional[_ReactionHistoryProvider] = ...,
    platform: Optional[str] = ...,
    channel: Optional[str] = ...,
    job: str = ...,
    permit_quota_ratio: Optional[float] = ...,
) -> Optional[_WeatherPost]: ...

__all__: tuple[str, ...]
