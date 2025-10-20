from __future__ import annotations

import inspect
from typing import Any, Optional, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ...features.weather.post_builder import ReactionHistoryProvider
else:
    from ...features.weather import ReactionHistoryProvider
from . import JobContext, ScheduledJob
from .common import (
    as_mapping,
    collect_schedules,
    get_float,
    is_enabled,
    optional_str,
    resolve_object,
)


def _resolve_history_provider(value: object) -> Optional[ReactionHistoryProvider]:
    if value is None:
        return None
    if isinstance(value, str):
        resolved = resolve_object(value)
        return cast(Optional[ReactionHistoryProvider], resolved)
    return cast(Optional[ReactionHistoryProvider], value)


def build_weather_jobs(context: JobContext) -> list[ScheduledJob]:
    weather_cfg = as_mapping(context.settings.get("weather"))
    if not weather_cfg or not is_enabled(weather_cfg):
        return []

    job_name = optional_str(weather_cfg.get("job")) or "weather"
    schedules = collect_schedules(weather_cfg, default="21:00")
    weather_priority_raw = weather_cfg.get("priority")
    priority = (
        int(get_float(weather_priority_raw, 5.0))
        if weather_priority_raw is not None
        else 5
    )
    weather_channel = (
        optional_str(weather_cfg.get("channel")) or context.default_channel
    )

    engagement_cfg = as_mapping(weather_cfg.get("engagement"))
    target_callable = getattr(
        context.build_weather_post,
        "__wrapped__",
        context.build_weather_post,
    )
    weather_params = inspect.signature(target_callable).parameters
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
            call_kwargs["channel"] = weather_channel
        if "job" in weather_params:
            call_kwargs["job"] = job_name
        return await context.build_weather_post(context.settings, **call_kwargs)

    return [
        ScheduledJob(
            name=job_name,
            func=job_weather,
            schedules=schedules,
            channel=weather_channel,
            priority=max(priority, 0),
        )
    ]
__all__ = ["build_weather_jobs"]
