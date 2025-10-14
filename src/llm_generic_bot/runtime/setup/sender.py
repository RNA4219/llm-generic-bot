from __future__ import annotations

from types import SimpleNamespace
from typing import Optional, cast

from ...core.orchestrator import Orchestrator
from ...core.types import Sender

PermitOverride = tuple[str, Optional[str], str]


def build_send_adapter(
    *,
    orchestrator: Orchestrator,
    platform: str,
    default_channel: Optional[str],
) -> tuple[Sender, dict[str, PermitOverride]]:
    permit_overrides: dict[str, PermitOverride] = {}
    _channel_unset = object()

    async def send(
        text: str,
        channel: object = _channel_unset,
        *,
        job: str = "weather",
    ) -> None:
        resolved_channel = (
            default_channel if channel is _channel_unset else cast(Optional[str], channel)
        )
        target_job = job
        target_platform = platform
        override = permit_overrides.get(job)
        if override is not None:
            override_platform, override_channel, override_job = override
            target_platform = override_platform or target_platform
            if override_channel is not None:
                resolved_channel = override_channel
            target_job = override_job
        await orchestrator.enqueue(
            text,
            job=target_job,
            platform=target_platform,
            channel=resolved_channel,
        )

    sender = cast(Sender, SimpleNamespace(send=send))
    return sender, permit_overrides
