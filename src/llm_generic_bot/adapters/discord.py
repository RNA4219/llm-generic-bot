from __future__ import annotations

import logging
import os
import uuid
from typing import Final

import httpx

from ._retry import RetryConfig, run_with_retry


class DiscordSender:
    def __init__(
        self,
        token: str | None = None,
        channel_id: str | None = None,
        *,
        retry_config: RetryConfig | None = None,
        logger: logging.Logger | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.token = token or os.getenv("DISCORD_BOT_TOKEN", "")
        self.channel_id = channel_id or os.getenv("DISCORD_CHANNEL_ID", "")
        self.base: Final[str] = "https://discord.com/api/v10"
        self.retry_config = retry_config or RetryConfig()
        self._logger = logger or logging.getLogger(__name__)
        self._timeout = timeout

    async def send(
        self,
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
    ) -> None:
        channel_id = channel or self.channel_id
        if not (self.token and channel_id):
            return

        url = f"{self.base}/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        payload = {"content": text}
        cid = correlation_id or str(uuid.uuid4())

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async def _attempt() -> httpx.Response:
                return await client.post(url, headers=headers, json=payload)

            await run_with_retry(
                adapter="discord",
                correlation_id=cid,
                target=channel_id,
                attempt=_attempt,
                retry_config=self.retry_config,
                logger=self._logger,
            )
