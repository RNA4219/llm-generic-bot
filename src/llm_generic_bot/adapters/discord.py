from __future__ import annotations
import os, httpx, asyncio

class DiscordSender:
    def __init__(self, token: str | None = None, channel_id: str | None = None):
        self.token = token or os.getenv("DISCORD_BOT_TOKEN","")
        self.channel_id = channel_id or os.getenv("DISCORD_CHANNEL_ID","")
        self.base = "https://discord.com/api/v10"

    async def send(self, text: str, channel: str | None = None) -> None:
        channel_id = channel or self.channel_id
        if not (self.token and channel_id): return
        url = f"{self.base}/channels/{channel_id}/messages"
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, headers={"Authorization": f"Bot {self.token}"}, json={"content": text})
