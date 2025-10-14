from __future__ import annotations

# LEGACY_SETUP_CHECKLIST
# - [ ] プロファイル別の送信者解決をコンフィグ駆動へ移行
# - [ ] ジョブ登録ロジックを宣言的なテーブル定義へ移設

import datetime as dt
from dataclasses import replace
from functools import wraps
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from ..adapters.discord import DiscordSender
from ..adapters.misskey import MisskeySender
from ..config.quotas import QuotaSettings, load_quota_settings
from ..core.arbiter import PermitGate
from ..core.cooldown import CooldownGate
from ..core.dedupe import NearDuplicateFilter
from ..core.orchestrator import (
    Orchestrator,
    PermitDecision,
    PermitDecisionLike,
    PermitEvaluator,
    Sender,
)
from ..core.queue import CoalesceQueue
from ..core.scheduler import Scheduler
from ..features.dm_digest import build_dm_digest
from ..features.news import build_news_post
from ..features.omikuji import build_omikuji_post
from ..features.report import WeeklyReportTemplate, generate_weekly_summary
from ..features.weather import build_weather_post
from ..infra import metrics as metrics_module
from ..infra.metrics import MetricsService
from .jobs import JobContext, ScheduledJob
from .jobs.common import (
    as_mapping,
    collect_schedules,
    get_float,
    optional_str,
    resolve_object,
)
from .jobs.dm_digest import build_dm_digest_jobs
from .jobs.news import build_news_jobs
from .jobs.omikuji import build_omikuji_jobs
from .jobs.weather import build_weather_jobs

_resolve_object = resolve_object

__all__ = [
    "setup_runtime",
    "_resolve_object",
    "build_weather_post",
    "build_news_post",
    "build_dm_digest",
    "build_omikuji_post",
]


def _build_cooldown(cooldown_cfg: Mapping[str, Any]) -> CooldownGate:
    coeff_cfg = as_mapping(cooldown_cfg.get("coeff"))
    return CooldownGate(
        int(get_float(cooldown_cfg.get("window_sec"), 1800)),
        get_float(cooldown_cfg.get("mult_min"), 1.0),
        get_float(cooldown_cfg.get("mult_max"), 6.0),
        get_float(coeff_cfg.get("rate"), 0.5),
        get_float(coeff_cfg.get("time"), 0.8),
        get_float(coeff_cfg.get("eng"), 0.6),
    )


def _build_dedupe(dedupe_cfg: Mapping[str, Any]) -> NearDuplicateFilter:
    return NearDuplicateFilter(
        k=int(get_float(dedupe_cfg.get("recent_k"), 20)),
        threshold=get_float(dedupe_cfg.get("sim_threshold"), 0.93),
    )


def _resolve_sender(
    profiles: Mapping[str, Any],
    *,
    sender: Optional[Sender],
) -> tuple[str, Optional[str], Sender]:
    discord_cfg = as_mapping(profiles.get("discord"))
    misskey_cfg = as_mapping(profiles.get("misskey"))
    if discord_cfg.get("enabled"):
        channel_value = discord_cfg.get("channel")
        default_channel: Optional[str] = (
            channel_value if isinstance(channel_value, str) else "default"
        )
        active_sender = sender or DiscordSender()
        return "discord", default_channel, active_sender
    channel_value = misskey_cfg.get("channel")
    default_channel = channel_value if isinstance(channel_value, str) else None
    active_sender = sender or MisskeySender()
    return "misskey", default_channel, active_sender


def _build_permit(
    quota: QuotaSettings,
    *,
    permit_gate: Optional[PermitGate],
) -> PermitEvaluator:
    gate = permit_gate or (PermitGate(per_channel=quota.per_channel) if quota.per_channel else None)

    if gate is None:

        def _permit_no_gate(
            _platform: str, _channel: Optional[str], job: str
        ) -> PermitDecisionLike:
            return cast(PermitDecisionLike, PermitDecision.allow(job))

        return cast(PermitEvaluator, _permit_no_gate)

    def _permit_with_gate(platform: str, channel: Optional[str], job: str) -> PermitDecisionLike:
        decision = gate.permit(platform, channel, job)
        if decision.allowed:
            return cast(
                PermitDecisionLike,
                PermitDecision.allow(decision.job or job),
            )
        return cast(
            PermitDecisionLike,
            PermitDecision(
                allowed=False,
                reason=decision.reason,
                retryable=decision.retryable,
                job=decision.job or job,
            ),
        )

    return cast(PermitEvaluator, _permit_with_gate)


def _register_job(
    scheduler: Scheduler,
    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]],
    job: ScheduledJob,
) -> None:
    jobs[job.name] = job.func
    for hhmm in job.schedules:
        scheduler.every_day(
            job.name,
            hhmm,
            job.func,
            channel=job.channel,
            priority=job.priority,
        )


_WEEKDAY_INDEX = {name: idx for idx, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}


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


def setup_runtime(
    settings: Mapping[str, Any],
    *,
    sender: Optional[Sender] = None,
    queue: Optional[CoalesceQueue] = None,
    permit_gate: Optional[PermitGate] = None,
) -> tuple[Scheduler, Orchestrator, dict[str, Callable[[], Awaitable[Optional[str]]]]]:
    cfg = dict(settings)
    tz = str(cfg.get("timezone", "Asia/Tokyo"))

    cooldown_cfg = as_mapping(cfg.get("cooldown"))
    cooldown = _build_cooldown(cooldown_cfg)
    dedupe_cfg = as_mapping(cfg.get("dedupe"))
    dedupe = _build_dedupe(dedupe_cfg)

    quota: QuotaSettings = load_quota_settings(cfg)
    permit = _build_permit(quota, permit_gate=permit_gate)

    profiles = as_mapping(cfg.get("profiles"))
    platform, default_channel, active_sender = _resolve_sender(
        profiles,
        sender=sender,
    )

    metrics_cfg = as_mapping(cfg.get("metrics"))
    metrics_service: Optional[MetricsService] = None
    metrics_module.set_retention_days(None)
    if metrics_cfg.get("backend", "memory") == "memory":
        retention_days = None
        retention_value = metrics_cfg.get("retention_days")
        if retention_value is not None:
            retention_candidate = int(get_float(retention_value, 7.0))
            retention_days = max(1, retention_candidate)
        if retention_days is not None:
            metrics_module.set_retention_days(retention_days)
            metrics_service = MetricsService(retention_days=retention_days)
        else:
            metrics_service = MetricsService()
    else:
        metrics_module.set_retention_days(None)

    orchestrator = Orchestrator(
        sender=active_sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
        metrics=metrics_service,
        platform=platform,
    )

    _CHANNEL_UNSET = object()
    permit_overrides: dict[str, tuple[str, Optional[str], str]] = {}

    @wraps(build_weather_post)
    async def _call_weather_post(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_weather_post(*args, **kwargs)

    @wraps(build_news_post)
    async def _call_news_post(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_news_post(*args, **kwargs)

    @wraps(build_omikuji_post)
    async def _call_omikuji_post(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_omikuji_post(*args, **kwargs)

    @wraps(build_dm_digest)
    async def _call_dm_digest(*args: Any, **kwargs: Any) -> Optional[str]:
        return await build_dm_digest(*args, **kwargs)

    async def send(
        text: str,
        channel: object = _CHANNEL_UNSET,
        *,
        job: str = "weather",
    ) -> None:
        resolved_channel = (
            default_channel if channel is _CHANNEL_UNSET else cast(Optional[str], channel)
        )
        target_job = job
        target_platform = platform
        override = permit_overrides.get(job)
        if override is not None:
            override_platform, override_channel, override_job = override
            target_platform = override_platform or target_platform
            if override_channel is not None:
                resolved_channel = override_channel
            target_job = override_job
        await orchestrator.enqueue(
            text,
            job=target_job,
            platform=target_platform,
            channel=resolved_channel,
        )

    scheduler = Scheduler(
        tz=tz,
        sender=cast(Sender, SimpleNamespace(send=send)),
        queue=queue,
    )

    context = JobContext(
        settings=cfg,
        scheduler=scheduler,
        platform=platform,
        default_channel=default_channel,
        cooldown=cooldown,
        permit=permit,
        build_weather_post=_call_weather_post,
        build_news_post=_call_news_post,
        build_omikuji_post=_call_omikuji_post,
        build_dm_digest=_call_dm_digest,
    )

    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]] = {}
    for factory in (
        build_weather_jobs,
        build_news_jobs,
        build_omikuji_jobs,
        build_dm_digest_jobs,
    ):
        for scheduled in factory(context):
            _register_job(scheduler, jobs, scheduled)

    report_cfg = as_mapping(cfg.get("report"))
    if report_cfg.get("enabled"):
        job_name = str(report_cfg.get("job", "weekly_report"))
        job_channel = optional_str(report_cfg.get("channel")) or default_channel
        job_priority = max(int(get_float(report_cfg.get("priority"), 5.0)), 0)
        template_cfg = as_mapping(report_cfg.get("template"))
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
        permit_cfg = as_mapping(report_cfg.get("permit"))
        permit_platform = str(permit_cfg.get("platform", platform))
        permit_channel = optional_str(permit_cfg.get("channel")) or job_channel
        permit_job = optional_str(permit_cfg.get("job")) or job_name
        permit_overrides[job_name] = (permit_platform, permit_channel, permit_job)

        raw_schedules = collect_schedules(report_cfg, default="09:00")
        parsed_schedules = tuple(_parse_weekday_schedule(value) for value in raw_schedules)

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
            line_context = {
                "start": start_text,
                "end": end_text,
                "week_range": week_range_text,
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
            locale = optional_str(report_cfg.get("locale")) or "default"
            fallback = optional_str(report_cfg.get("fallback")) or ""
            payload = generate_weekly_summary(
                replace(snapshot, start=start_local, end=end_local),
                locale=locale,
                fallback=fallback,
                failure_threshold=get_float(report_cfg.get("failure_threshold"), 0.5),
                templates={
                    locale: summary_template
                },
            )
            severity = payload.tags.get("severity") if isinstance(payload.tags, Mapping) else None
            message_parts = [line for line in payload.body.splitlines() if line]
            if severity == "normal":
                header_line = message_parts.pop(0) if message_parts else None
                footer_line = (
                    message_parts.pop() if footer_template and message_parts else None
                )
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

    return scheduler, orchestrator, jobs
