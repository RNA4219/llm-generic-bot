from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from ...adapters.discord import DiscordSender
from ...adapters.misskey import MisskeySender
from ...core.orchestrator import Orchestrator, Sender
from ...core.scheduler import Scheduler
from ...features.report import ReportPayload, WeeklyReportTemplate, generate_weekly_summary
from ...infra import metrics as metrics_module
from ..jobs.common import as_mapping, collect_schedules, get_float, optional_str


__all__ = [
    "register_weekly_report_job",
    "resolve_sender",
]


def resolve_sender(
    profiles: Mapping[str, Any],
    *,
    sender: Optional[Sender],
) -> tuple[str, Optional[str], Sender]:
    discord_cfg = as_mapping(profiles.get("discord"))
    misskey_cfg = as_mapping(profiles.get("misskey"))
    if discord_cfg.get("enabled"):
        channel_value = discord_cfg.get("channel")
        default_channel: Optional[str]
        if isinstance(channel_value, str):
            default_channel = channel_value
        else:
            default_channel = None
        active_sender = sender or DiscordSender()
        return "discord", default_channel, active_sender
    channel_value = misskey_cfg.get("channel")
    default_channel = channel_value if isinstance(channel_value, str) else None
    active_sender = sender or MisskeySender()
    return "misskey", default_channel, active_sender


_WEEKDAY_INDEX = {
    name: idx
    for idx, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
}


def _parse_weekday_schedule(value: str) -> tuple[Optional[frozenset[int]], str]:
    tokens = value.strip().split()
    if not tokens:
        return None, "09:00"
    hhmm = tokens[-1]
    if len(tokens) == 1:
        return None, hhmm
    weekday_tokens = " ".join(tokens[:-1])
    weekdays: set[int] = set()
    for raw_token in weekday_tokens.replace(",", " ").split():
        if not raw_token:
            continue
        index = _WEEKDAY_INDEX.get(raw_token[:3].lower())
        if index is None:
            weekdays.clear()
            break
        weekdays.add(index)
    return (frozenset(weekdays), hhmm) if weekdays else (None, hhmm)


def _wrap_weekday_job(
    job: Callable[[], Awaitable[Optional[str]]],
    *,
    weekdays: Optional[frozenset[int]],
    scheduler: Scheduler,
) -> Callable[[], Awaitable[Optional[str]]]:
    if not weekdays:
        return job

    async def _wrapped() -> Optional[str]:
        now = getattr(scheduler, "_test_now", None)
        current = now if isinstance(now, dt.datetime) else dt.datetime.now(scheduler.tz)
        return await job() if current.weekday() in weekdays else None

    return _wrapped


def register_weekly_report_job(
    *,
    config: Mapping[str, Any],
    scheduler: Scheduler,
    orchestrator: Orchestrator,
    default_channel: Optional[str],
    platform: str,
    permit_overrides: dict[str, tuple[str, Optional[str], str]],
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]],
    summary_factory: Callable[..., ReportPayload] = generate_weekly_summary,
) -> None:
    if not config.get("enabled"):
        return

    job_name = str(config.get("job", "weekly_report"))
    job_channel = optional_str(config.get("channel")) or default_channel
    job_priority = max(int(get_float(config.get("priority"), 5.0)), 0)
    template_cfg = as_mapping(config.get("template"))
    raw_title = template_cfg.get("title")
    title_template = raw_title if isinstance(raw_title, str) else "{week_range}"
    raw_line = template_cfg.get("line")
    line_template = raw_line if isinstance(raw_line, str) else "{label}: {value}"
    footer_template = optional_str(template_cfg.get("footer"))
    summary_template = WeeklyReportTemplate(
        title=title_template,
        line=line_template,
        footer=footer_template,
    )
    permit_cfg = as_mapping(config.get("permit"))
    permit_platform = str(permit_cfg.get("platform", platform))
    permit_channel = optional_str(permit_cfg.get("channel")) or job_channel
    permit_job = optional_str(permit_cfg.get("job")) or job_name
    permit_overrides[job_name] = (permit_platform, permit_channel, permit_job)

    raw_schedules = collect_schedules(config, default="09:00")
    parsed_schedules = tuple(_parse_weekday_schedule(value) for value in raw_schedules)
    locale = optional_str(config.get("locale")) or "default"
    fallback = optional_str(config.get("fallback")) or ""
    failure_threshold = get_float(config.get("failure_threshold"), 0.5)

    async def job_weekly_report() -> Optional[str]:
        snapshot = await orchestrator.weekly_snapshot()
        metrics_data = metrics_module.weekly_snapshot()
        start_dt = snapshot.start
        end_dt = snapshot.end
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=dt.timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=dt.timezone.utc)
        start_local = start_dt.astimezone(scheduler.tz)
        end_local = end_dt.astimezone(scheduler.tz)
        success_rate = metrics_data.get("success_rate")
        lines: list[str] = []
        start_text = start_local.date().isoformat()
        end_text = end_local.date().isoformat()
        week_range_text = f"{start_text}〜{end_text}"
        success_total = sum(
            snapshot_entry.count
            for snapshot_entry in snapshot.counters.get("send.success", {}).values()
        )
        failure_total = sum(
            snapshot_entry.count
            for snapshot_entry in snapshot.counters.get("send.failure", {}).values()
        )
        processed_total = success_total + failure_total

        channel_counts: dict[str, int] = {}
        for metric_name in ("send.success", "send.failure"):
            for tags_key, counter_snapshot in snapshot.counters.get(metric_name, {}).items():
                channel_value = next(
                    (value for key, value in tags_key if key == "channel"),
                    None,
                )
                if channel_value:
                    channel_counts[channel_value] = (
                        channel_counts.get(channel_value, 0) + counter_snapshot.count
                    )
        top_channel_name = "-"
        if channel_counts:
            top_channel_name = max(channel_counts.items(), key=lambda item: item[1])[0]

        success_rate_pct = (success_total / processed_total * 100.0) if processed_total else 0.0
        failure_rate_pct = (failure_total / processed_total * 100.0) if processed_total else 0.0

        line_context = {
            "start": start_text,
            "end": end_text,
            "week_range": week_range_text,
            "total": processed_total,
            "success": success_total,
            "failure": failure_total,
            "success_rate": success_rate_pct,
            "failure_rate": failure_rate_pct,
            "top_channel": top_channel_name,
        }
        if isinstance(success_rate, Mapping):
            for name, payload in sorted(success_rate.items()):
                if name == permit_job or name == job_name:
                    continue
                if not isinstance(payload, Mapping):
                    continue
                ratio_value = payload.get("ratio")
                if not isinstance(ratio_value, (int, float)):
                    continue
                lines.append(
                    summary_template.format_line(
                        metric=f"{name} success",
                        value=f"{float(ratio_value):.0%}",
                        **line_context,
                    )
                )
        if not lines:
            total = sum(
                entry.count for series in snapshot.counters.values() for entry in series.values()
            )
            if total:
                lines.append(
                    summary_template.format_line(
                        metric="events",
                        value=str(total),
                        **line_context,
                    )
                )
        payload = summary_factory(
            replace(snapshot, start=start_local, end=end_local),
            locale=locale,
            fallback=fallback,
            failure_threshold=failure_threshold,
            templates={
                locale: summary_template
            },
        )
        severity = payload.tags.get("severity") if isinstance(payload.tags, Mapping) else None
        message_parts = [line for line in payload.body.splitlines() if line]
        if severity == "normal":
            header_line = message_parts.pop(0) if message_parts else None
            footer_line = message_parts.pop() if footer_template and message_parts else None
            composed: list[str] = []
            if header_line:
                composed.append(header_line)
            if lines:
                composed.extend(lines)
            if message_parts:
                composed.extend(message_parts)
            if footer_line is not None:
                composed.append(footer_line)
            message_parts = composed
        if not message_parts:
            return None
        return "\n".join(message_parts)

    jobs[job_name] = job_weekly_report
    for weekdays, hhmm in parsed_schedules:
        wrapped = cast(
            Callable[[], Awaitable[Optional[str]]],
            _wrap_weekday_job(job_weekly_report, weekdays=weekdays, scheduler=scheduler),
        )
        scheduler.every_day(
            job_name,
            hhmm,
            wrapped,  # type: ignore[arg-type]
            channel=job_channel,
            priority=job_priority,
        )
