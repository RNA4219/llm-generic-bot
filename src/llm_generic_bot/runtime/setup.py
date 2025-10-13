from __future__ import annotations

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
from ..features.dm_digest import (
    DMSender,
    LogCollector,
    SummaryProvider as DigestSummaryProvider,
    build_dm_digest,
)
from ..features.news import build_news_post as _build_news_post
from ..features.omikuji import build_omikuji_post
from ..features.weather import build_weather_post as _build_weather_post
from .jobs import register_news_job, register_weather_job
from .jobs.helpers import (
    as_mapping as _as_mapping,
    collect_schedules as _collect_schedules,
    is_enabled as _is_enabled,
    optional_str as _optional_str,
    resolve_configured_object as _resolve_configured_object,
    resolve_object as _resolve_object,
)

__all__ = [
    "setup_runtime",
    "build_weather_post",
    "build_news_post",
    "build_dm_digest",
    "build_omikuji_post",
]

build_weather_post = _build_weather_post
build_news_post = _build_news_post


_resolve_reference = _resolve_object


def setup_runtime(
    settings: Mapping[str, Any],
    *,
    sender: Optional[Sender] = None,
    queue: Optional[CoalesceQueue] = None,
    permit_gate: Optional[PermitGate] = None,
) -> tuple[Scheduler, Orchestrator, dict[str, Callable[[], Awaitable[Optional[str]]]]]:
    cfg = dict(settings)
    tz = str(cfg.get("timezone", "Asia/Tokyo"))
    cooldown_cfg = _as_mapping(cfg.get("cooldown"))

    def _num(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    coeff_cfg = _as_mapping(cooldown_cfg.get("coeff"))
    cooldown = CooldownGate(
        int(_num(cooldown_cfg.get("window_sec"), 1800)),
        _num(cooldown_cfg.get("mult_min"), 1.0),
        _num(cooldown_cfg.get("mult_max"), 6.0),
        _num(coeff_cfg.get("rate"), 0.5),
        _num(coeff_cfg.get("time"), 0.8),
        _num(coeff_cfg.get("eng"), 0.6),
    )
    dedupe_cfg = _as_mapping(cfg.get("dedupe"))
    dedupe = NearDuplicateFilter(
        k=int(_num(dedupe_cfg.get("recent_k"), 20)),
        threshold=_num(dedupe_cfg.get("sim_threshold"), 0.93),
    )
    quota: QuotaSettings = load_quota_settings(cfg)
    gate = permit_gate or (PermitGate(per_channel=quota.per_channel) if quota.per_channel else None)

    if gate is None:

        def _permit_no_gate(
            _platform: str, _channel: Optional[str], job: str
        ) -> PermitDecisionLike:
            return cast(PermitDecisionLike, PermitDecision.allow(job))

        permit = cast(PermitEvaluator, _permit_no_gate)

    else:

        def _permit_with_gate(
            platform: str, channel: Optional[str], job: str
        ) -> PermitDecisionLike:
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

        permit = cast(PermitEvaluator, _permit_with_gate)

    profiles = _as_mapping(cfg.get("profiles"))
    discord_cfg = _as_mapping(profiles.get("discord"))
    misskey_cfg = _as_mapping(profiles.get("misskey"))
    default_channel: Optional[str]
    if discord_cfg.get("enabled"):
        platform = "discord"
        channel_value = discord_cfg.get("channel")
        default_channel = channel_value if isinstance(channel_value, str) else "default"
        active_sender: Sender = sender or DiscordSender()
    else:
        platform = "misskey"
        channel_value = misskey_cfg.get("channel")
        default_channel = channel_value if isinstance(channel_value, str) else None
        active_sender = sender or MisskeySender()

    orchestrator = Orchestrator(
        sender=active_sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
    )

    _CHANNEL_UNSET = object()

    async def send(
        text: str,
        channel: object = _CHANNEL_UNSET,
        *,
        job: str = "weather",
    ) -> None:
        resolved_channel = (
            default_channel if channel is _CHANNEL_UNSET else cast(Optional[str], channel)
        )
        await orchestrator.enqueue(
            text,
            job=job,
            platform=platform,
            channel=resolved_channel,
        )

    scheduler = Scheduler(tz=tz, sender=cast(Sender, SimpleNamespace(send=send)), queue=queue)
    weather_cfg = _as_mapping(cfg.get("weather"))
    weather_job_name, weather_job = register_weather_job(
        scheduler=scheduler,
        config=weather_cfg,
        global_config=cfg,
        cooldown=cooldown,
        platform=platform,
        default_channel=default_channel,
    )

    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]] = {
        weather_job_name: weather_job
    }

    news_cfg = _as_mapping(cfg.get("news"))
    news_job = register_news_job(
        scheduler=scheduler,
        config=news_cfg,
        default_channel=default_channel,
        cooldown=cooldown,
        platform=platform,
    )
    if news_job is not None:
        job_name, job_callable = news_job
        jobs[job_name] = job_callable

    omikuji_cfg = _as_mapping(cfg.get("omikuji"))
    if omikuji_cfg and _is_enabled(omikuji_cfg):
        user_id = _optional_str(omikuji_cfg.get("user_id"))
        if user_id:
            job_name = str(omikuji_cfg.get("job", "omikuji"))
            omikuji_priority = max(int(_num(omikuji_cfg.get("priority"), 5.0)), 0)
            omikuji_channel = _optional_str(omikuji_cfg.get("channel")) or default_channel

            async def job_omikuji() -> Optional[str]:
                return await build_omikuji_post(cfg, user_id=user_id)

            jobs[job_name] = job_omikuji
            for hhmm in _collect_schedules(omikuji_cfg, default="09:00"):
                scheduler.every_day(
                    job_name,
                    hhmm,
                    job_omikuji,
                    channel=omikuji_channel,
                    priority=omikuji_priority,
                )

    dm_cfg = _as_mapping(cfg.get("dm_digest"))
    if dm_cfg and _is_enabled(dm_cfg):
        dm_log_provider = _resolve_configured_object(
            dm_cfg.get("log_provider"),
            context="dm_digest.log_provider",
        )
        dm_summary_provider = _resolve_configured_object(
            dm_cfg.get("summary_provider") or dm_cfg.get("summarizer"),
            context="dm_digest.summary_provider",
        )
        dm_sender = _resolve_configured_object(
            dm_cfg.get("sender"),
            context="dm_digest.sender",
        )
        if (
            dm_log_provider is not None
            and dm_summary_provider is not None
            and dm_sender is not None
        ):
            job_name = str(dm_cfg.get("job", "dm_digest"))
            dm_priority = max(int(_num(dm_cfg.get("priority"), 5.0)), 0)
            dm_channel = _optional_str(dm_cfg.get("channel"))

            async def job_dm_digest() -> Optional[str]:
                await build_dm_digest(
                    dm_cfg,
                    log_provider=cast(LogCollector, dm_log_provider),
                    summarizer=cast(DigestSummaryProvider, dm_summary_provider),
                    sender=cast(DMSender, dm_sender),
                    permit=permit,
                )
                return None

            jobs[job_name] = job_dm_digest
            for hhmm in _collect_schedules(dm_cfg, default="22:00"):
                scheduler.every_day(
                    job_name,
                    hhmm,
                    job_dm_digest,
                    channel=dm_channel,
                    priority=dm_priority,
                )

    return scheduler, orchestrator, jobs

