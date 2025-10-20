from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, cast

_PACKAGE_PATH = Path(__file__).with_name("weather")
__path__ = [str(_PACKAGE_PATH)]
if __spec__ is not None:
    __spec__.submodule_search_locations = __path__

cache = import_module(".weather.cache", __package__)
engagement = import_module(".weather.engagement", __package__)
post_builder = import_module(".weather.post_builder", __package__)

if TYPE_CHECKING:
    from ..core.cooldown import CooldownGate
    from .weather.post_builder import ReactionHistoryProvider as _ReactionHistoryProvider
    from .weather.post_builder import WeatherPost as _WeatherPost
else:
    CooldownGate = Any  # type: ignore[assignment]
    _ReactionHistoryProvider = Any  # type: ignore[assignment]
    _WeatherPost = Any  # type: ignore[assignment]

# LEGACY_WEATHER_MODULE_REFACTOR_CHECKLIST:
# - Keep this facade in place until dependent call sites only rely on the thin wrapper.
# - Remove the legacy file once cache, engagement, and post builder modules stabilise.
LEGACY_WEATHER_MODULE_REFACTOR_CHECKLIST = (
    "Maintain weather.py as a facade until downstream modules stop touching internals.",
    "Verify cache.py, engagement.py, and post_builder.py cover all unit/integration tests before removal.",
    "Document removal steps in TASKS.md once legacy file deletion is safe.",
)

CACHE: Path = cache.DEFAULT_CACHE_PATH
ReactionHistoryProvider = cast(
    type[_ReactionHistoryProvider], getattr(post_builder, "ReactionHistoryProvider")
)
WeatherPost = cast(type[_WeatherPost], getattr(post_builder, "WeatherPost"))


async def build_weather_post(
    cfg: Mapping[str, Any],
    *,
    cooldown: Optional[CooldownGate] = None,
    reaction_history_provider: Optional[ReactionHistoryProvider] = None,
    platform: Optional[str] = None,
    channel: Optional[str] = None,
    job: str = "weather",
    permit_quota_ratio: Optional[float] = None,
) -> Optional[WeatherPost]:
    return await post_builder.build_weather_post(
        cfg,
        cooldown=cooldown,
        reaction_history_provider=reaction_history_provider,
        platform=platform,
        channel=channel,
        job=job,
        permit_quota_ratio=permit_quota_ratio,
        cache_path=CACHE,
    )


__all__ = [
    "CACHE",
    "LEGACY_WEATHER_MODULE_REFACTOR_CHECKLIST",
    "ReactionHistoryProvider",
    "WeatherPost",
    "build_weather_post",
    "cache",
    "engagement",
    "post_builder",
]
