from __future__ import annotations

# LEGACY_SETUP_CHECKLIST
# - [ ] プロファイル別の送信者解決をコンフィグ駆動へ移行
# - [ ] ジョブ登録ロジックを宣言的なテーブル定義へ移設

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
from ..features.weather import build_weather_post
from .jobs import JobContext, ScheduledJob
from .jobs.common import as_mapping, get_float, resolve_object
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

    orchestrator = Orchestrator(
        sender=active_sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit,
    )

    _CHANNEL_UNSET = object()

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
        await orchestrator.enqueue(
            text,
            job=job,
            platform=platform,
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

    return scheduler, orchestrator, jobs
