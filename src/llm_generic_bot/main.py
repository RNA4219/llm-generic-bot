from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from .adapters.discord import DiscordSender
from .adapters.misskey import MisskeySender
from .config.loader import Settings
from .config.quotas import QuotaSettings, load_quota_settings
from .core.arbiter import PermitGate
from .core.cooldown import CooldownGate
from .core.dedupe import NearDuplicateFilter
from .core.orchestrator import Orchestrator, PermitDecision, PermitDecisionLike, Sender
from .core.queue import CoalesceQueue
from .core.scheduler import Scheduler
from .features.dm_digest import build_dm_digest
from .features.news import build_news_post
from .features.omikuji import build_omikuji_post
from .features.weather import build_weather_post

def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_enabled(config: Mapping[str, Any], *, default: bool = True) -> bool:
    flag = config.get("enabled")
    if flag is None:
        return default
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, (int, float)):
        return bool(flag)
    if isinstance(flag, str):
        lowered = flag.strip().lower()
        if lowered in {"", "0", "false", "off"}:
            return False
        if lowered in {"1", "true", "on"}:
            return True
    return default


def _schedule_values(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple, set)):
        return [str(value) for value in raw if isinstance(value, str) and value]
    return []


def _collect_schedules(config: Mapping[str, Any], *, default: str) -> list[str]:
    schedules = _schedule_values(config.get("schedule"))
    schedules.extend(_schedule_values(config.get("schedules")))
    return schedules or [default]


def _optional_str(value: object) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


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
        _num(coeff_cfg.get("rate"), 0.5), _num(coeff_cfg.get("time"), 0.8), _num(coeff_cfg.get("eng"), 0.6),
    )
    dedupe_cfg = _as_mapping(cfg.get("dedupe"))
    dedupe = NearDuplicateFilter(k=int(_num(dedupe_cfg.get("recent_k"), 20)), threshold=_num(dedupe_cfg.get("sim_threshold"), 0.93))
    quota: QuotaSettings = load_quota_settings(cfg)
    gate = permit_gate or (PermitGate(per_channel=quota.per_channel) if quota.per_channel else None)

    permit: Callable[[str, Optional[str], str], PermitDecisionLike]
    if gate is None:
        def permit(
            _platform: str, _channel: Optional[str], job: str
        ) -> PermitDecisionLike:
            return PermitDecision.allowed(job)
    else:
        def permit(
            platform: str, channel: Optional[str], job: str
        ) -> PermitDecisionLike:
            decision = gate.permit(platform, channel, job)
            if decision.allowed:
                return PermitDecision.allowed(decision.job or job)
            return PermitDecision(
                allowed=False,
                reason=decision.reason,
                retryable=decision.retryable,
                job=decision.job or job,
            )

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

    orchestrator = Orchestrator(sender=active_sender, cooldown=cooldown, dedupe=dedupe, permit=permit)

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
    schedule_value = weather_cfg.get("schedule")
    schedule = schedule_value if isinstance(schedule_value, str) else "21:00"
    async def job_weather() -> Optional[str]:
        return await build_weather_post(cfg)

    weather_priority_raw = weather_cfg.get("priority")
    weather_priority = int(_num(weather_priority_raw, 5.0)) if weather_priority_raw is not None else 5
    scheduler.every_day(
        "weather",
        schedule,
        job_weather,
        channel=default_channel,
        priority=max(weather_priority, 0),
    )

    jobs: dict[str, Callable[[], Awaitable[Optional[str]]]] = {"weather": job_weather}

    news_cfg = _as_mapping(cfg.get("news"))
    if news_cfg and _is_enabled(news_cfg):
        feed_provider = news_cfg.get("feed_provider")
        summary_provider = news_cfg.get("summary_provider")
        if feed_provider and summary_provider:
            job_name = str(news_cfg.get("job", "news"))
            news_priority = max(int(_num(news_cfg.get("priority"), 5.0)), 0)
            news_channel = _optional_str(news_cfg.get("channel")) or default_channel

            async def job_news() -> Optional[str]:
                platform_name = platform
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
                        normalized_job or "-",
                    )
                    history = cooldown.history.get(key)
                    if history is None:
                        return False
                    cutoff = time.time() - cooldown.window
                    while history and history[0] < cutoff:
                        history.popleft()
                    return bool(history)

                return await build_news_post(
                    news_cfg,
                    feed_provider=feed_provider,
                    summary_provider=summary_provider,
                    permit=_permit_hook,
                    cooldown=_cooldown_check,
                )

            jobs[job_name] = job_news
            for hhmm in _collect_schedules(news_cfg, default="21:00"):
                scheduler.every_day(
                    job_name,
                    hhmm,
                    job_news,
                    channel=news_channel,
                    priority=news_priority,
                )

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
        log_provider = dm_cfg.get("log_provider")
        summary_provider = dm_cfg.get("summary_provider") or dm_cfg.get("summarizer")
        dm_sender = dm_cfg.get("sender")
        if log_provider and summary_provider and dm_sender:
            job_name = str(dm_cfg.get("job", "dm_digest"))
            dm_priority = max(int(_num(dm_cfg.get("priority"), 5.0)), 0)
            dm_channel = _optional_str(dm_cfg.get("channel"))

            async def job_dm_digest() -> Optional[str]:
                result = await build_dm_digest(
                    dm_cfg,
                    log_provider=log_provider,
                    summarizer=summary_provider,
                    sender=dm_sender,
                    permit=permit,
                )
                if result and getattr(scheduler, "_active_job", None) is not None:
                    scheduler.queue.push(
                        result,
                        priority=dm_priority,
                        job=job_name,
                        channel=dm_channel,
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


async def main() -> None:
    scheduler, orchestrator, _ = setup_runtime(Settings("config/settings.json").data)
    try:
        await scheduler.run_forever()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
