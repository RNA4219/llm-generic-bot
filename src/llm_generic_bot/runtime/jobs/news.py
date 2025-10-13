from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol, cast

from ...core.cooldown import CooldownGate
from ...core.scheduler import Scheduler
from ...features.news import (
    FeedProvider,
    SummaryProvider,
    build_news_post as _default_news_builder,
)
from .helpers import collect_schedules, is_enabled, optional_str, resolve_configured_object

NewsJob = Callable[[], Awaitable[Optional[str]]]


class NewsPostBuilder(Protocol):
    async def __call__(
        self,
        cfg: Mapping[str, Any],
        *,
        feed_provider: FeedProvider,
        summary_provider: SummaryProvider,
        permit: Callable[..., None] | None = None,
        cooldown: Callable[..., Awaitable[bool]] | None = None,
    ) -> Optional[str]:
        ...

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

    def _resolve_builder() -> NewsPostBuilder:
        try:
            from .. import setup as runtime_setup  # type: ignore[import-not-found]
        except Exception:
            return cast(NewsPostBuilder, _default_news_builder)
        builder = getattr(runtime_setup, "build_news_post", None)
        if builder is None:
            return cast(NewsPostBuilder, _default_news_builder)
        return cast(NewsPostBuilder, builder)

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

        builder = _resolve_builder()
        return await builder(
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
