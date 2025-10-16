from __future__ import annotations

from typing import Callable, Mapping, Optional

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator

from .conftest import (
    DummyCooldown,
    DummyDedupe,
    DummySender,
    PermitDecision,
    RecordingMetrics,
    _SendRequest,
    metrics_module,
)

pytestmark = pytest.mark.anyio("asyncio")


async def test_process_denied(
    monkeypatch: pytest.MonkeyPatch,
    make_orchestrator: Callable[..., Orchestrator],
    dummy_sender: DummySender,
    dummy_cooldown: DummyCooldown,
    dummy_dedupe: DummyDedupe,
    recording_metrics: RecordingMetrics,
    capture_events: tuple[
        list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]],
        Callable[..., None],
    ],
) -> None:
    sender = dummy_sender
    cooldown = dummy_cooldown
    dedupe = dummy_dedupe
    metrics = recording_metrics
    denied: list[dict[str, object]] = []

    def fake_report_permit_denied(
        *,
        job: str,
        platform: str,
        channel: Optional[str],
        reason: str,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        denied.append(
            {
                "job": job,
                "platform": platform,
                "channel": channel,
                "reason": reason,
                "permit_tags": dict(permit_tags) if permit_tags else None,
            }
        )

    monkeypatch.setattr(metrics_module, "report_permit_denied", fake_report_permit_denied)

    orchestrator = await make_orchestrator(
        sender=sender,
        cooldown=cooldown,
        dedupe=dedupe,
        permit=lambda *_: PermitDecision(False, "blocked", False, "job-denied"),
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
            correlation_id="corr-denied",
        )
    )

    assert not sender.sent
    assert not cooldown.calls
    assert not dedupe.checked
    assert denied == [
        {
            "job": "job-denied",
            "platform": "discord",
            "channel": "general",
            "reason": "blocked",
            "permit_tags": {"retryable": "false"},
        }
    ]
    assert events == [
        (
            "send.denied",
            {
                "job": "job-denied",
                "platform": "discord",
                "channel": "general",
                "retryable": "false",
            },
            None,
            {
                "correlation_id": "corr-denied",
                "reason": "blocked",
                "retryable": False,
            },
            False,
        )
    ]
