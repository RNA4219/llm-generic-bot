from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from .adapters.discord import DiscordSender
from .adapters.misskey import MisskeySender
from .config.loader import Settings
from .config.quotas import QuotaSettings, load_quota_settings
from .core.arbiter import PermitGate
from .core.cooldown import CooldownGate
from .core.dedupe import NearDuplicateFilter
from .core.orchestrator import Orchestrator, PermitDecision, Sender
from .core.queue import CoalesceQueue
from .core.scheduler import Scheduler
from .features.weather import build_weather_post

def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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

    permit: Callable[[str, Optional[str], str], PermitDecision]
    if gate is None:
        def permit(_platform: str, _channel: Optional[str], job: str) -> PermitDecision:
            return PermitDecision.allowed(job)
    else:
        def permit(platform: str, channel: Optional[str], job: str) -> PermitDecision:
            decision = gate.permit(platform, channel)
            return PermitDecision.allowed(job) if decision.allowed else PermitDecision(False, decision.reason, job)

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

    async def send(text: str, channel: Optional[str] = None) -> None:
        await orchestrator.enqueue(text, job="weather", platform=platform, channel=channel or default_channel)

    scheduler = Scheduler(tz=tz, sender=cast(Sender, SimpleNamespace(send=send)), queue=queue)
    weather_cfg = _as_mapping(cfg.get("weather"))
    schedule_value = weather_cfg.get("schedule")
    schedule = schedule_value if isinstance(schedule_value, str) else "21:00"
    async def job_weather() -> Optional[str]:
        return await build_weather_post(cfg)

    scheduler.every_day("weather", schedule, job_weather, channel=default_channel)
    return scheduler, orchestrator, {"weather": job_weather}


async def main() -> None:
    scheduler, orchestrator, _ = setup_runtime(Settings("config/settings.json").data)
    try:
        await scheduler.run_forever()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
