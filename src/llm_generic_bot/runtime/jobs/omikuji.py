from __future__ import annotations

from typing import Optional

from . import JobContext, ScheduledJob
from .common import as_mapping, collect_schedules, get_float, is_enabled, optional_str


def build_omikuji_jobs(context: JobContext) -> list[ScheduledJob]:
    omikuji_cfg = as_mapping(context.settings.get("omikuji"))
    if not omikuji_cfg or not is_enabled(omikuji_cfg):
        return []

    user_id = optional_str(omikuji_cfg.get("user_id"))
    if not user_id:
        return []

    job_name = str(omikuji_cfg.get("job", "omikuji"))
    priority = max(int(get_float(omikuji_cfg.get("priority"), 5.0)), 0)
    channel = optional_str(omikuji_cfg.get("channel")) or context.default_channel

    async def job_omikuji() -> Optional[str]:
        return await context.build_omikuji_post(context.settings, user_id=user_id)

    return [
        ScheduledJob(
            name=job_name,
            func=job_omikuji,
            schedules=collect_schedules(omikuji_cfg, default="09:00"),
            channel=channel,
            priority=priority,
        )
    ]


__all__ = ["build_omikuji_jobs"]
