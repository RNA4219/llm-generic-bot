from __future__ import annotations
import os, httpx, asyncio

class MisskeySender:
    def __init__(self, instance: str | None = None, token: str | None = None):
        self.instance = instance or os.getenv("MISSKEY_INSTANCE","misskey.io")
        self.token = token or os.getenv("MISSKEY_TOKEN","")

    async def send(self, text: str, channel: str | None = None) -> None:
        if not (self.instance and self.token): return
        url = f"https://{self.instance}/api/notes/create"
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, json={"i": self.token, "text": text})
