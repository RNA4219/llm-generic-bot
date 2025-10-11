from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Tuple, cast

from .adapters.discord import DiscordSender
from .adapters.misskey import MisskeySender
from .config.loader import Settings
from .config.quotas import load_quota_settings
from .core.arbiter import PermitGate
from .core.cooldown import CooldownGate
from .core.dedupe import NearDuplicateFilter
from .core.orchestrator import Orchestrator, PermitDecision, PermitEvaluator, Sender as OrchestratorSender
from .core.queue import CoalesceQueue
from .core.scheduler import Scheduler
from .features.weather import build_weather_post

SleepFn = Callable[[float], Awaitable[None]]
NowFn = Callable[[], float]


def _resolve_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _resolve_channel(profile: Mapping[str, Any]) -> str:
    channel = profile.get("channel", "default")
    return str(channel)


def bootstrap_main(
    settings: Mapping[str, Any],
    *,
    sender: OrchestratorSender | None = None,
    queue_window_seconds: float | None = None,
    queue_threshold: int | None = None,
    sleep: SleepFn | None = None,
    now: NowFn | None = None,
) -> Tuple[Scheduler, Orchestrator]:
    tz = str(settings.get("timezone", "Asia/Tokyo"))

    cooldown_raw = _resolve_mapping(settings.get("cooldown", {}))
    coeff_raw = _resolve_mapping(cooldown_raw.get("coeff", {}))
    cooldown = CooldownGate(
        int(cooldown_raw.get("window_sec", 1800)),
        float(cooldown_raw.get("mult_min", 1.0)),
        float(cooldown_raw.get("mult_max", 6.0)),
        float(coeff_raw.get("rate", 0.5)),
        float(coeff_raw.get("time", 0.8)),
        float(coeff_raw.get("eng", 0.6)),
    )

    dedupe_raw = _resolve_mapping(settings.get("dedupe", {}))
    dedupe = NearDuplicateFilter(
        k=int(dedupe_raw.get("recent_k", 20)),
        threshold=float(dedupe_raw.get("sim_threshold", 0.93)),
    )

    quota_settings = load_quota_settings(settings)
    permit_gate: PermitGate | None = None
    if quota_settings.per_channel is not None:
        permit_gate = PermitGate(per_channel=quota_settings.per_channel, time_fn=now)

    profiles_raw = _resolve_mapping(settings.get("profiles", {}))
    discord_profile = _resolve_mapping(profiles_raw.get("discord", {}))
    misskey_profile = _resolve_mapping(profiles_raw.get("misskey", {}))
    use_discord = bool(discord_profile.get("enabled"))
    platform = "discord" if use_discord else "misskey"
    active_channel = _resolve_channel(discord_profile if use_discord else misskey_profile)

    active_sender: OrchestratorSender
    if sender is None:
        discord_sender = DiscordSender()
        misskey_sender = MisskeySender()
        active_sender = discord_sender if use_discord else misskey_sender
    else:
        active_sender = sender

    def permit(platform_name: str, channel: Optional[str], job: str) -> PermitDecision:
        if permit_gate is None:
            return PermitDecision.allow(job)
        raw = permit_gate.permit(platform_name, channel or "-")
        if raw.allowed:
            return PermitDecision.allow(job)
        return PermitDecision(False, raw.reason, job)

    permit_fn = cast(PermitEvaluator, permit)

    orchestrator = Orchestrator(
        sender=active_sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=permit_fn,
        platform=platform,
    )

    queue = CoalesceQueue(
        window_seconds=queue_window_seconds if queue_window_seconds is not None else 180.0,
        threshold=queue_threshold if queue_threshold is not None else 3,
    )

    scheduler_kwargs: dict[str, Any] = {
        "tz": tz,
        "sender": orchestrator,
        "queue": queue,
    }
    if sleep is not None:
        scheduler_kwargs["sleep"] = sleep
    scheduler = Scheduler(**scheduler_kwargs)

    weather_raw = _resolve_mapping(settings.get("weather", {}))
    schedule = str(weather_raw.get("schedule", "21:00"))

    async def weather_job() -> str:
        settings_payload = cast(Dict[str, Any], dict(settings))
        return await build_weather_post(settings_payload)

    scheduler.every_day("weather", schedule, weather_job, channel=active_channel)

    return scheduler, orchestrator


async def main() -> None:
    cfg = Settings("config/settings.json").data
    scheduler, orchestrator = bootstrap_main(cfg)
    try:
        await scheduler.run_forever()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
