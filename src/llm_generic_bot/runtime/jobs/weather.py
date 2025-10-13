from __future__ import annotations

import inspect
from typing import Any, Optional, cast

from ...features.weather import ReactionHistoryProvider
from . import JobContext, ScheduledJob
from .common import as_mapping, get_float, resolve_object


def _resolve_history_provider(value: object) -> Optional[ReactionHistoryProvider]:
    if value is None:
        return None
    if isinstance(value, str):
        resolved = resolve_object(value)
        return cast(Optional[ReactionHistoryProvider], resolved)
    return cast(Optional[ReactionHistoryProvider], value)


def build_weather_jobs(context: JobContext) -> list[ScheduledJob]:
    weather_cfg = as_mapping(context.settings.get("weather"))

    schedule_value = weather_cfg.get("schedule")
    schedule = schedule_value if isinstance(schedule_value, str) else "21:00"
    weather_priority_raw = weather_cfg.get("priority")
    priority = (
        int(get_float(weather_priority_raw, 5.0))
        if weather_priority_raw is not None
        else 5
    )

    engagement_cfg = as_mapping(weather_cfg.get("engagement"))
    weather_params = inspect.signature(context.build_weather_post).parameters
    history_provider: Optional[ReactionHistoryProvider] = None
    if "reaction_history_provider" in weather_params:
        provider_value = engagement_cfg.get("history_provider")
        history_provider = _resolve_history_provider(provider_value)

    async def job_weather() -> Optional[str]:
        call_kwargs: dict[str, Any] = {}
        if (
            history_provider is not None
            and "reaction_history_provider" in weather_params
        ):
            call_kwargs["reaction_history_provider"] = history_provider
            if "cooldown" in weather_params:
                call_kwargs["cooldown"] = context.cooldown
            if "platform" in weather_params:
                call_kwargs["platform"] = context.platform
            if "channel" in weather_params:
                call_kwargs["channel"] = context.default_channel
            if "job" in weather_params:
                call_kwargs["job"] = "weather"
        return await context.build_weather_post(context.settings, **call_kwargs)

    return [
        ScheduledJob(
            name="weather",
            func=job_weather,
            schedules=(schedule,),
            channel=context.default_channel,
            priority=max(priority, 0),
        )
    ]
__all__ = ["build_weather_jobs"]
