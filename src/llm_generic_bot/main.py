from __future__ import annotations
import os, asyncio, datetime as dt
from .config.loader import Settings
from .core.scheduler import Scheduler
from .core.cooldown import CooldownGate
from .core.arbiter import next_slot
from .core.dedupe import NearDuplicateFilter
from .adapters.discord import DiscordSender
from .adapters.misskey import MisskeySender
from .features.weather import build_weather_post

async def main():
    cfg = Settings("config/settings.json").data
    tz = cfg.get("timezone","Asia/Tokyo")
    sched = Scheduler(tz=tz)
    # senders
    discord = DiscordSender()
    misskey = MisskeySender()
    # choose active profile (Discordを既定)
    active_sender = discord if (cfg.get("profiles",{}).get("discord",{}).get("enabled")) else misskey

    # cooldown
    cd_cfg = cfg.get("cooldown",{})
    gate = CooldownGate(cd_cfg.get("window_sec",1800), cd_cfg.get("mult_min",1.0), cd_cfg.get("mult_max",6.0),
                        cd_cfg.get("coeff",{}).get("rate",0.5), cd_cfg.get("coeff",{}).get("time",0.8), cd_cfg.get("coeff",{}).get("eng",0.6))
    dedupe = NearDuplicateFilter(k=cfg.get("dedupe",{}).get("recent_k",20), threshold=cfg.get("dedupe",{}).get("sim_threshold",0.93))

    async def job_weather():
        text = await build_weather_post(cfg)
        # dedupe
        if not dedupe.permit(text): return
        await active_sender.send(text)
        gate.note_post("discord","default","weather")

    # schedule weather
    wcfg = cfg.get("weather",{})
    sched.every_day("weather", wcfg.get("schedule","21:00"), job_weather)

    await sched.run_forever()

if __name__ == "__main__":
    asyncio.run(main())
