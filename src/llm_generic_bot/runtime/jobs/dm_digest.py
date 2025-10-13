from __future__ import annotations

from typing import Optional, cast

from ...features.dm_digest import DMSender, LogCollector, SummaryProvider
from . import JobContext, ScheduledJob
from .common import as_mapping, collect_schedules, get_float, is_enabled, optional_str, resolve_configured_object


def build_dm_digest_jobs(context: JobContext) -> list[ScheduledJob]:
    dm_cfg = as_mapping(context.settings.get("dm_digest"))
    if not dm_cfg or not is_enabled(dm_cfg):
        return []

    dm_log_provider = resolve_configured_object(
        dm_cfg.get("log_provider"),
        context="dm_digest.log_provider",
    )
    dm_summary_provider = resolve_configured_object(
        dm_cfg.get("summary_provider") or dm_cfg.get("summarizer"),
        context="dm_digest.summary_provider",
    )
    dm_sender = resolve_configured_object(
        dm_cfg.get("sender"),
        context="dm_digest.sender",
    )
    if (
        dm_log_provider is None
        or dm_summary_provider is None
        or dm_sender is None
    ):
        return []

    job_name = str(dm_cfg.get("job", "dm_digest"))
    priority = max(int(get_float(dm_cfg.get("priority"), 5.0)), 0)
    channel = optional_str(dm_cfg.get("channel"))

    async def job_dm_digest() -> Optional[str]:
        await context.build_dm_digest(
            dm_cfg,
            log_provider=cast(LogCollector, dm_log_provider),
            summarizer=cast(SummaryProvider, dm_summary_provider),
            sender=cast(DMSender, dm_sender),
            permit=context.permit,
        )
        return None

    return [
        ScheduledJob(
            name=job_name,
            func=job_dm_digest,
            schedules=collect_schedules(dm_cfg, default="22:00"),
            channel=channel,
            priority=priority,
        )
    ]


__all__ = ["build_dm_digest_jobs"]
