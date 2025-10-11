from __future__ import annotations
from typing import Dict, Any, Callable
import anyio, asyncio, datetime as dt, zoneinfo

class Scheduler:
    def __init__(self, tz: str = "Asia/Tokyo"):
        self.tz = zoneinfo.ZoneInfo(tz)
        self.jobs: list[tuple[str, str, Callable[[], Any]]] = []  # (name, "HH:MM", coro)
    def every_day(self, name: str, hhmm: str, coro: Callable[[], Any]) -> None:
        self.jobs.append((name, hhmm, coro))

    async def run_forever(self):
        while True:
            now = dt.datetime.now(self.tz)
            hhmm = now.strftime("%H:%M")
            for name, t, job in self.jobs:
                if t == hhmm:
                    asyncio.create_task(job())
            await anyio.sleep(60 - now.second)
