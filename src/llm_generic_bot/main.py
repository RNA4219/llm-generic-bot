from __future__ import annotations

import asyncio

from .adapters.discord import DiscordSender
from .adapters.misskey import MisskeySender
from .config.loader import Settings
from .core.cooldown import CooldownGate
from .core.dedupe import NearDuplicateFilter
from .core.orchestrator import Orchestrator, PermitDecision
from .core.scheduler import Scheduler
from .features.weather import build_weather_post


class _AllowAllPermit:
    def __call__(self, platform: str, channel: str | None, job: str) -> PermitDecision:
        return PermitDecision.allowed(job)


async def main() -> None:
    cfg = Settings("config/settings.json").data
    tz = cfg.get("timezone", "Asia/Tokyo")
    sched = Scheduler(tz=tz)

    discord = DiscordSender()
    misskey = MisskeySender()
    profiles = cfg.get("profiles", {})
    discord_enabled = profiles.get("discord", {}).get("enabled")
    active_sender = discord if discord_enabled else misskey
    active_platform = "discord" if discord_enabled else "misskey"
    active_channel = profiles.get(active_platform, {}).get("channel", "default")

    cd_cfg = cfg.get("cooldown", {})
    gate = CooldownGate(
        cd_cfg.get("window_sec", 1800),
        cd_cfg.get("mult_min", 1.0),
        cd_cfg.get("mult_max", 6.0),
        cd_cfg.get("coeff", {}).get("rate", 0.5),
        cd_cfg.get("coeff", {}).get("time", 0.8),
        cd_cfg.get("coeff", {}).get("eng", 0.6),
    )
    dedupe = NearDuplicateFilter(
        k=cfg.get("dedupe", {}).get("recent_k", 20),
        threshold=cfg.get("dedupe", {}).get("sim_threshold", 0.93),
    )
    tz = cfg.get("timezone","Asia/Tokyo")
    # senders
    discord = DiscordSender()
    misskey = MisskeySender()
    # choose active profile (Discordを既定)
    active_sender = discord if (cfg.get("profiles",{}).get("discord",{}).get("enabled")) else misskey
    sched = Scheduler(tz=tz, sender=active_sender)

    orchestrator = Orchestrator(
        sender=active_sender,
        cooldown=gate,
        dedupe=dedupe,
        permit=_AllowAllPermit(),
    )

    async def job_weather() -> None:
        text = await build_weather_post(cfg)
        await orchestrator.enqueue(
            text,
            job="weather",
            platform=active_platform,
            channel=active_channel,
        )

    wcfg = cfg.get("weather", {})
    sched.every_day("weather", wcfg.get("schedule", "21:00"), job_weather)
    async def job_weather() -> str | None:
        text = await build_weather_post(cfg)
        # dedupe
        if not dedupe.permit(text):
            return None
        gate.note_post("discord","default","weather")
        return text

    try:
        await sched.run_forever()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
