from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Mapping

from llm_generic_bot.core.orchestrator import Orchestrator
from llm_generic_bot.infra import make_metrics_recorder
from llm_generic_bot.infra.metrics import (
    CounterSnapshot,
    ObservationSnapshot,
    InMemoryMetricsService,
)


def _clock_from(iterator: Iterator[datetime]) -> Callable[[], datetime]:
    def _inner() -> datetime:
        return next(iterator)

    return _inner


def test_collect_weekly_snapshot_filters_and_groups() -> None:
    base = datetime(2024, 1, 8, tzinfo=timezone.utc)
    clock_values = iter(
        [
            base - timedelta(days=8),
            base - timedelta(days=1),
            base - timedelta(hours=2),
            base,
        ]
    )
    service = InMemoryMetricsService(clock=_clock_from(clock_values))
    recorder = make_metrics_recorder(service)

    recorder.increment(
        "send.success",
        tags={"job": "weather", "platform": "slack"},
    )
    recorder.increment(
        "send.success",
        tags={"job": "weather", "platform": "slack"},
    )
    recorder.observe(
        "send.latency",
        0.75,
        tags={"job": "weather", "platform": "slack"},
    )

    snapshot = asyncio.run(service.collect_weekly_snapshot())

    key = (("job", "weather"), ("platform", "slack"))
    assert snapshot.counters["send.success"][key] == CounterSnapshot(count=1)
    assert snapshot.observations["send.latency"][key] == ObservationSnapshot(
        count=1,
        minimum=0.75,
        maximum=0.75,
        total=0.75,
        average=0.75,
    )


class _DummyCooldownGate:
    def note_post(self, platform: str, channel: str, job: str) -> None:  # noqa: D401
        return None


class _DummyDedupe:
    def permit(self, text: str) -> bool:  # noqa: D401
        return True


class _DummySender:
    def __init__(self) -> None:
        self._behaviour: list[Exception | None] = []

    def schedule(self, behaviour: Exception | None) -> None:
        self._behaviour.append(behaviour)

    async def send(self, text: str, channel: str | None, *, job: str) -> None:
        outcome = self._behaviour.pop(0)
        if outcome is not None:
            raise outcome


class _PermitDecision:
    def __init__(
        self,
        *,
        allowed: bool,
        reason: str | None = None,
        retryable: bool = True,
        job: str | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.retryable = retryable
        self.job = job


class _PermitEvaluator:
    def __init__(self, decisions: list[_PermitDecision]) -> None:
        self._decisions = decisions

    def __call__(self, platform: str, channel: str | None, job: str) -> _PermitDecision:
        return self._decisions.pop(0)


class _RecordingMetricsService(InMemoryMetricsService):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, Mapping[str, str] | None, Mapping[str, float] | None, Mapping[str, object] | None]] = []

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.events.append((name, tags, measurements, metadata))
        super().record_event(
            name,
            tags=tags,
            measurements=measurements,
            metadata=metadata,
        )


def test_orchestrator_records_metrics_events() -> None:
    async def _run() -> list[tuple[str, Mapping[str, str] | None, Mapping[str, float] | None, Mapping[str, object] | None]]:
        metrics_service = _RecordingMetricsService()
        sender = _DummySender()
        sender.schedule(None)
        sender.schedule(RuntimeError("boom"))

        permit = _PermitEvaluator(
            [
                _PermitDecision(allowed=True, job="weather"),
                _PermitDecision(allowed=True, job="weather"),
                _PermitDecision(allowed=False, reason="blocked", retryable=False, job="weather"),
            ]
        )

        orchestrator = Orchestrator(
            sender=sender,
            cooldown=_DummyCooldownGate(),
            dedupe=_DummyDedupe(),
            permit=permit,
            metrics=metrics_service,
            platform="slack",
        )

        try:
            await orchestrator.send("ok", channel="alerts", job="weather")
            await orchestrator.send("oops", channel="alerts", job="weather")
            await orchestrator.send("deny", channel="alerts", job="weather")
        finally:
            await orchestrator.close()

        return [event for event in metrics_service.events if event[3] is not None]

    recorded = asyncio.run(_run())
    assert [name for name, *_ in recorded] == [
        "send.success",
        "send.failure",
        "send.denied",
    ]
    tags = [event[1] for event in recorded]
    assert all(tagset and tagset.get("job") == "weather" for tagset in tags)
    assert tags[0]["channel"] == "alerts"
