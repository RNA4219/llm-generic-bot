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
        if token:
            self.token = token
        else:
            env_token = os.getenv("DISCORD_BOT_TOKEN")
            self.token = env_token or ""

        if channel_id:
            self.channel_id = channel_id
        else:
            env_channel = os.getenv("DISCORD_CHANNEL_ID")
            self.channel_id = env_channel or ""
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
        recipient_id: str | None = None,
    ) -> None:
        if not self.token:
            return

        headers = {"Authorization": f"Bot {self.token}"}
        cid = correlation_id or str(uuid.uuid4())

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if recipient_id:
                channel_id = await self._open_dm_channel(
                    client,
                    headers=headers,
                    recipient_id=recipient_id,
                    correlation_id=cid,
                )
                target = recipient_id
            else:
                channel_id = channel or self.channel_id
                target = channel_id

            if not channel_id:
                return

            url = f"{self.base}/channels/{channel_id}/messages"
            payload = {"content": text}

            async def _attempt() -> httpx.Response:
                return await client.post(url, headers=headers, json=payload)

            await run_with_retry(
                adapter="discord",
                correlation_id=cid,
                target=target or "-",
                attempt=_attempt,
                retry_config=self.retry_config,
                logger=self._logger,
            )

    async def _open_dm_channel(
        self,
        client: httpx.AsyncClient,
        *,
        headers: dict[str, str],
        recipient_id: str,
        correlation_id: str,
    ) -> str:
        response = await client.post(
            f"{self.base}/users/@me/channels",
            headers=headers,
            json={"recipient_id": recipient_id},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            self._logger.warning(
                "discord_dm_open_failed",
                extra={
                    "event": "discord_dm_open_failed",
                    "correlation_id": correlation_id,
                    "recipient": recipient_id,
                    "status": response.status_code,
                },
            )
            raise

        data = response.json()
        channel_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(channel_id, str) or not channel_id:
            self._logger.error(
                "discord_dm_open_invalid",
                extra={
                    "event": "discord_dm_open_invalid",
                    "correlation_id": correlation_id,
                    "recipient": recipient_id,
                },
            )
            raise RuntimeError("invalid dm channel response")
        return channel_id
