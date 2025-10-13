from __future__ import annotations

import time
from typing import Optional, cast

from ...features.news import FeedProvider, SummaryProvider as NewsSummaryProvider
from . import JobContext, ScheduledJob
from .common import (
    as_mapping,
    collect_schedules,
    get_float,
    is_enabled,
    optional_str,
    resolve_configured_object,
)


def build_news_jobs(context: JobContext) -> list[ScheduledJob]:
    news_cfg = as_mapping(context.settings.get("news"))
    if not news_cfg or not is_enabled(news_cfg):
        return []

    news_feed_provider = resolve_configured_object(
        news_cfg.get("feed_provider"),
        context="news.feed_provider",
    )
    news_summary_provider = resolve_configured_object(
        news_cfg.get("summary_provider"),
        context="news.summary_provider",
    )
    if news_feed_provider is None or news_summary_provider is None:
        return []

    job_name = str(news_cfg.get("job", "news"))
    news_priority = max(int(get_float(news_cfg.get("priority"), 5.0)), 0)
    news_channel = optional_str(news_cfg.get("channel")) or context.default_channel

    async def job_news() -> Optional[str]:
        platform_name = context.platform
        state = {"suppress_cooldown": bool(news_cfg.get("suppress_cooldown", False))}

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
            history = context.cooldown.history.get(key)
            if history is None:
                return False
            cutoff = time.time() - context.cooldown.window
            while history and history[0] < cutoff:
                history.popleft()
            return bool(history)

        return await context.build_news_post(
            news_cfg,
            feed_provider=cast(FeedProvider, news_feed_provider),
            summary_provider=cast(NewsSummaryProvider, news_summary_provider),
            permit=_permit_hook,
            cooldown=_cooldown_check,
        )

    return [
        ScheduledJob(
            name=job_name,
            func=job_news,
            schedules=collect_schedules(news_cfg, default="21:00"),
            channel=news_channel,
            priority=news_priority,
        )
    ]


__all__ = ["build_news_jobs"]
