from __future__ import annotations

from typing import Any, cast

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator
from llm_generic_bot.runtime.setup.runtime_helpers import resolve_sender
from llm_generic_bot.runtime.setup.sender import build_send_adapter


class _StubOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(
        self,
        text: str,
        *,
        job: str,
        platform: str,
        channel: str | None,
    ) -> str:
        self.calls.append(
            {"text": text, "job": job, "platform": platform, "channel": channel}
        )
        return "corr"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_resolve_sender_discord_channel_defaults_to_none() -> None:
    profiles = {"discord": {"enabled": True}}

    platform, default_channel, sender = resolve_sender(profiles, sender=None)

    assert platform == "discord"
    assert default_channel is None

    stub_orchestrator = _StubOrchestrator()
    scheduler_sender, permit_overrides = build_send_adapter(
        orchestrator=cast(Orchestrator, stub_orchestrator),
        platform=platform,
        default_channel=default_channel,
    )

    assert permit_overrides == {}

    await scheduler_sender.send("hello", job="sample")

    assert stub_orchestrator.calls == [
        {"text": "hello", "job": "sample", "platform": "discord", "channel": None}
    ]

    await sender.send("world", channel=None, job="sample")

