from __future__ import annotations

import asyncio
from collections import Counter
from typing import Callable, Mapping, MutableMapping, Optional

import pytest

import llm_generic_bot.core.orchestrator as orchestrator_module
from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import (
    MetricsRecorder,
    Orchestrator,
    PermitDecision,
    _SendRequest,
)

metrics_module = orchestrator_module.metrics_module


class DummyCooldown(CooldownGate):
    def __init__(self) -> None:
        self.calls: list[tuple[str, Optional[str], str]] = []

    def note_post(self, platform: str, channel: Optional[str], job: str) -> None:  # type: ignore[override]
        self.calls.append((platform, channel, job))


class DummyDedupe(NearDuplicateFilter):
    def __init__(self, *, allowed: bool = True) -> None:
        super().__init__(k=5, threshold=0.5)
        self.allowed = allowed
        self.checked: list[str] = []

    def permit(self, text: str) -> bool:  # type: ignore[override]
        self.checked.append(text)
        return self.allowed


class DummySender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Optional[str], str]] = []

    async def send(
        self,
        text: str,
        channel: Optional[str] = None,
        *,
        job: Optional[str] = None,
    ) -> None:
        await asyncio.sleep(0)
        self.sent.append((text, channel, job or ""))


class RecordingMetrics(MetricsRecorder):
    def __init__(self) -> None:
        self.counts: MutableMapping[str, Counter[tuple[tuple[str, str], ...]]] = {}
        self.observations: dict[str, list[tuple[Mapping[str, str] | None, float]]] = {}

    @staticmethod
    def _normalize(tags: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
        if not tags:
            return ()
        return tuple(sorted(tags.items()))

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        counter = self.counts.setdefault(name, Counter())
        counter[self._normalize(tags)] += 1

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        bucket = self.observations.setdefault(name, [])
        bucket.append((dict(tags) if tags else None, value))


def _capture_events() -> tuple[
    list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]],
    Callable[..., None],
]:
    recorded: list[
        tuple[
            str,
            Mapping[str, str],
            Mapping[str, float] | None,
            Mapping[str, object] | None,
            bool,
        ]
    ] = []

    def _recorder(
        name: str,
        tags: Mapping[str, str],
        *,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> None:
        recorded.append(
            (
                name,
                dict(tags),
                dict(measurements) if measurements else None,
                dict(metadata) if metadata else None,
                force,
            )
        )

    return recorded, _recorder


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def make_orchestrator() -> Callable[..., Orchestrator]:
    created: list[Orchestrator] = []

    async def _factory(**kwargs: object) -> Orchestrator:
        orchestrator = Orchestrator(**kwargs)
        created.append(orchestrator)
        return orchestrator

    yield _factory

    for orchestrator in created:
        await orchestrator.close()


@pytest.fixture
def dummy_sender() -> DummySender:
    return DummySender()


@pytest.fixture
def dummy_cooldown() -> DummyCooldown:
    return DummyCooldown()


@pytest.fixture
def dummy_dedupe() -> DummyDedupe:
    return DummyDedupe()


@pytest.fixture
def recording_metrics() -> RecordingMetrics:
    return RecordingMetrics()


@pytest.fixture
def capture_events() -> tuple[
    list[tuple[str, Mapping[str, str], Mapping[str, float] | None, Mapping[str, object] | None, bool]],
    Callable[..., None],
]:
    return _capture_events()


__all__ = [
    "DummyCooldown",
    "DummyDedupe",
    "DummySender",
    "PermitDecision",
    "RecordingMetrics",
    "_SendRequest",
    "_capture_events",
    "capture_events",
    "dummy_cooldown",
    "dummy_dedupe",
    "dummy_sender",
    "make_orchestrator",
    "metrics_module",
    "recording_metrics",
]
