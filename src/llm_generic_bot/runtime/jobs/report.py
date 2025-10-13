from __future__ import annotations

import datetime as dt
from typing import Iterable, Mapping, Optional, Sequence

from ...core.orchestrator import Orchestrator
from ...features.report import WeeklyReportTemplate, generate_weekly_summary
from . import JobContext, ScheduledJob
from .common import as_mapping, collect_schedules, get_float, optional_str

_WEEKDAY_ALIASES: Mapping[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def build_report_jobs(
    context: JobContext,
    *,
    orchestrator: Orchestrator,
    permit_overrides: dict[str, tuple[str, Optional[str], str]],
) -> list[ScheduledJob]:
    report_cfg = as_mapping(context.settings.get("report"))
    if not report_cfg or not report_cfg.get("enabled"):
        return []

    job_name = str(report_cfg.get("job", "weekly_report"))
    job_channel = optional_str(report_cfg.get("channel")) or context.default_channel
    job_priority = max(int(get_float(report_cfg.get("priority"), 5.0)), 0)
    locale = str(report_cfg.get("locale", "ja"))
    failure_threshold = max(0.0, min(get_float(report_cfg.get("failure_threshold"), 0.5), 1.0))

    template_cfg = as_mapping(report_cfg.get("template"))
    fallback = str(template_cfg.get("fallback", "No weekly summary available"))
    template = WeeklyReportTemplate(
        header=str(
            template_cfg.get("header")
            or template_cfg.get("title")
            or "📊 Weekly summary {start}–{end}"
        ),
        summary=str(
            template_cfg.get("summary")
            or template_cfg.get("line")
            or "Processed {total} / Success {success} / Failure {failure} (Success {success_rate:.1f}%)"
        ),
        channels=str(template_cfg.get("channels", "Top channels: {channels}")),
        failures=str(template_cfg.get("failures", "Top failures: {failures}")),
    )
    templates = {locale: template}

    permit_cfg = as_mapping(report_cfg.get("permit"))
    permit_platform = str(permit_cfg.get("platform", context.platform))
    permit_channel = optional_str(permit_cfg.get("channel")) or job_channel
    permit_job = optional_str(permit_cfg.get("job")) or job_name
    permit_overrides[job_name] = (permit_platform, permit_channel, permit_job)

    schedule_specs = _parse_schedule_entries(
        collect_schedules(report_cfg, default="Monday 09:00")
    )
    schedules = tuple(spec[1] for spec in schedule_specs)

    async def job_weekly_report() -> Optional[str]:
        now = dt.datetime.now(context.scheduler.tz)
        if not _matches_weekday(schedule_specs, now.weekday()):
            return None
        snapshot = await orchestrator.weekly_snapshot()
        payload = generate_weekly_summary(
            snapshot,
            locale=locale,
            fallback=fallback,
            failure_threshold=failure_threshold,
            templates=templates,
        )
        message = payload.body.strip()
        if not message:
            return None
        target_channel = payload.channel or job_channel
        permit_overrides[job_name] = (permit_platform, target_channel, permit_job)
        return message

    return [
        ScheduledJob(
            name=job_name,
            func=job_weekly_report,
            schedules=schedules,
            channel=job_channel,
            priority=job_priority,
        )
    ]


def _parse_schedule_entries(values: Sequence[str]) -> tuple[tuple[Optional[int], str], ...]:
    specs: list[tuple[Optional[int], str]] = []
    for value in values:
        tokens = value.strip().split()
        if not tokens:
            continue
        hhmm = tokens[-1]
        weekday: Optional[int] = None
        if len(tokens) > 1:
            key = tokens[0].lower()
            weekday = _WEEKDAY_ALIASES.get(key)
        specs.append((weekday, hhmm))
    return tuple(specs or [(None, "09:00")])


def _matches_weekday(
    specs: Iterable[tuple[Optional[int], str]],
    weekday: int,
) -> bool:
    for expected, _ in specs:
        if expected is None or expected == weekday:
            return True
    return False


__all__ = ["build_report_jobs"]
