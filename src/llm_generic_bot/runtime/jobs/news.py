from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from ...core.cooldown import CooldownGate
from ...core.scheduler import Scheduler
from ...features.news import FeedProvider, SummaryProvider, build_news_post
from .helpers import collect_schedules, is_enabled, optional_str, resolve_configured_object

NewsJob = Callable[[], Awaitable[Optional[str]]]


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def register_news_job(
    *,
    scheduler: Scheduler,
    config: Mapping[str, Any],
    default_channel: Optional[str],
    cooldown: CooldownGate,
    platform: str,
) -> tuple[str, NewsJob] | None:
    if not config or not is_enabled(config):
        return None

    news_feed_provider = resolve_configured_object(
        config.get("feed_provider"),
        context="news.feed_provider",
    )
    news_summary_provider = resolve_configured_object(
        config.get("summary_provider"),
        context="news.summary_provider",
    )
    if news_feed_provider is None or news_summary_provider is None:
        return None

    job_name = str(config.get("job", "news"))
    news_priority = max(int(_to_float(config.get("priority"), 5.0)), 0)
    news_channel = optional_str(config.get("channel")) or default_channel

    async def job_news() -> Optional[str]:
        platform_name = platform
        state = {"suppress_cooldown": bool(config.get("suppress_cooldown", False))}

        def _permit_hook(*, job: str, suppress_cooldown: bool) -> None:
            state["suppress_cooldown"] = suppress_cooldown

        async def _cooldown_check(
            *,
            job: str,
            platform: Optional[str],
            channel: Optional[str],
        ) -> bool:
            if state["suppress_cooldown"]:
                return False
            normalized_job = job or job_name
            normalized_platform = platform if platform is not None else platform_name
            normalized_channel = channel if channel is not None else news_channel
            key = (
                (normalized_platform or "-"),
                (normalized_channel or "-"),
                (normalized_job or "-"),
            )
            history = cooldown.history.get(key)
            if history is None:
                return False
            cutoff = time.time() - cooldown.window
            while history and history[0] < cutoff:
                history.popleft()
            return bool(history)

        return await build_news_post(
            config,
            feed_provider=cast(FeedProvider, news_feed_provider),
            summary_provider=cast(SummaryProvider, news_summary_provider),
            permit=_permit_hook,
            cooldown=_cooldown_check,
        )

    for hhmm in collect_schedules(config, default="21:00"):
        scheduler.every_day(
            job_name,
            hhmm,
            job_news,
            channel=news_channel,
            priority=news_priority,
        )

    return job_name, job_news
