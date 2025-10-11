from __future__ import annotations

import logging
import os
import uuid

import httpx

from ._retry import RetryConfig, run_with_retry


class MisskeySender:
    def __init__(
        self,
        instance: str | None = None,
        token: str | None = None,
        *,
        retry_config: RetryConfig | None = None,
        logger: logging.Logger | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.instance = instance or os.getenv("MISSKEY_INSTANCE", "misskey.io")
        self.token = token or os.getenv("MISSKEY_TOKEN", "")
        self.retry_config = retry_config or RetryConfig()
        self._logger = logger or logging.getLogger(__name__)
        self._timeout = timeout

    async def send(
        self,
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        if not (self.instance and self.token):
            return

        url = f"https://{self.instance}/api/notes/create"
        payload = {"i": self.token, "text": text}
        if channel:
            payload["channelId"] = channel
        cid = correlation_id or str(uuid.uuid4())

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async def _attempt() -> httpx.Response:
                return await client.post(url, json=payload)

            await run_with_retry(
                adapter="misskey",
                correlation_id=cid,
                target=self.instance,
                attempt=_attempt,
                retry_config=self.retry_config,
                logger=self._logger,
            )
