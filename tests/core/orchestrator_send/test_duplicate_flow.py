from __future__ import annotations

from collections import Counter
from typing import Callable, Mapping

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator

from .conftest import (
    DummyCooldown,
    DummyDedupe,
    DummySender,
    PermitDecision,
    RecordingMetrics,
    _SendRequest,
)

pytestmark = pytest.mark.anyio("asyncio")


async def test_process_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    make_orchestrator: Callable[..., Orchestrator],
    dummy_sender: DummySender,
    dummy_cooldown: DummyCooldown,
    recording_metrics: RecordingMetrics,
    capture_events: tuple[
        list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]],
        Callable[..., None],
    ],
) -> None:
    sender = dummy_sender
    cooldown = dummy_cooldown
    dedupe = DummyDedupe(allowed=False)
    metrics = recording_metrics

    orchestrator = await make_orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision.allow(),
        metrics=metrics,
        platform="discord",
    )
    events, recorder = capture_events
    monkeypatch.setattr(orchestrator, "_record_event", recorder)

    await orchestrator._process(
        _SendRequest(
            text="hello",
            job="weather",
            platform="discord",
            channel="general",
            correlation_id="corr-dup",
        )
    )

    assert sender.sent == []
    assert cooldown.calls == []
    assert dedupe.checked == ["hello"]
    assert metrics.counts == {
        "send.duplicate": Counter(
            {
                (
                    ("channel", "general"),
                    ("job", "weather"),
                    ("platform", "discord"),
                    ("retryable", "false"),
                    ("status", "duplicate"),
                ): 1
            }
        )
    }
    assert events == [
        (
            "send.duplicate",
            {
                "job": "weather",
                "platform": "discord",
                "channel": "general",
                "status": "duplicate",
                "retryable": "false",
            },
            None,
            {
                "correlation_id": "corr-dup",
                "status": "duplicate",
                "retryable": False,
            },
            False,
        )
    ]
