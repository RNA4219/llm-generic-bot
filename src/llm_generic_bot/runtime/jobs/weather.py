from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from ...core.cooldown import CooldownGate
from ...core.scheduler import Scheduler
from ...features.weather import ReactionHistoryProvider, build_weather_post
from .helpers import resolve_history_provider

WeatherJob = Callable[[], Awaitable[Optional[str]]]


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def register_weather_job(
    *,
    scheduler: Scheduler,
    config: Mapping[str, Any],
    global_config: Mapping[str, Any],
    cooldown: CooldownGate,
    platform: str,
    default_channel: Optional[str],
) -> tuple[str, WeatherJob]:
    schedule_value = config.get("schedule")
    schedule = schedule_value if isinstance(schedule_value, str) else "21:00"
    weather_params = inspect.signature(build_weather_post).parameters
    engagement_cfg = config.get("engagement")
    engagement = engagement_cfg if isinstance(engagement_cfg, Mapping) else {}
    history_provider: Optional[ReactionHistoryProvider] = None
    if "reaction_history_provider" in weather_params:
        history_provider = resolve_history_provider(engagement.get("history_provider"))

    settings_payload = cast(dict[str, Any], global_config)

    async def job_weather() -> Optional[str]:
        call_kwargs: dict[str, Any] = {}
        if (
            history_provider is not None
            and "reaction_history_provider" in weather_params
        ):
            call_kwargs["reaction_history_provider"] = history_provider
            if "cooldown" in weather_params:
                call_kwargs["cooldown"] = cooldown
            if "platform" in weather_params:
                call_kwargs["platform"] = platform
            if "channel" in weather_params:
                call_kwargs["channel"] = default_channel
            if "job" in weather_params:
                call_kwargs["job"] = "weather"
        return await build_weather_post(settings_payload, **call_kwargs)

    priority_raw = config.get("priority")
    priority = int(_to_float(priority_raw, 5.0)) if priority_raw is not None else 5
    scheduler.every_day(
        "weather",
        schedule,
        job_weather,
        channel=default_channel,
        priority=max(priority, 0),
    )
    return "weather", job_weather
