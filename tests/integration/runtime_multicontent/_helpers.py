from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.core.scheduler import Scheduler


__all__ = [
    "QueuePushCall",
    "EnqueueCall",
    "create_queue",
    "freeze_scheduler",
    "record_queue_push",
    "record_orchestrator_enqueue",
]


@dataclass
class QueuePushCall:
    text: str
    priority: int
    job: str
    created_at: Optional[float]
    channel: Optional[str]


@dataclass
class EnqueueCall:
    text: str
    job: str
    platform: str
    channel: Optional[str]
    correlation_id: Optional[str]


def create_queue() -> CoalesceQueue:
    return CoalesceQueue(window_seconds=0.0, threshold=1)


def freeze_scheduler(monkeypatch: pytest.MonkeyPatch, scheduler: Scheduler) -> None:
    scheduler.jitter_enabled = False

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(scheduler, "_sleep", no_sleep, raising=False)


def record_queue_push(
    monkeypatch: pytest.MonkeyPatch,
    scheduler: Scheduler,
) -> List[QueuePushCall]:
    calls: List[QueuePushCall] = []
    original_push = scheduler.queue.push

    def spy_push(
        text: str,
        *,
        priority: int,
        job: str,
        created_at: Optional[float] = None,
        channel: Optional[str] = None,
    ) -> None:
        calls.append(
            QueuePushCall(
                text=text,
                priority=priority,
                job=job,
                created_at=created_at,
                channel=channel,
            )
        )
        original_push(
            text,
            priority=priority,
            job=job,
            created_at=created_at,
            channel=channel,
        )

    monkeypatch.setattr(scheduler.queue, "push", spy_push)
    return calls


def record_orchestrator_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    orchestrator: Orchestrator,
) -> List[EnqueueCall]:
    calls: List[EnqueueCall] = []

    async def spy_enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        calls.append(
            EnqueueCall(
                text=text,
                job=job,
                platform=platform,
                channel=channel,
                correlation_id=correlation_id,
            )
        )
        return "corr"

    monkeypatch.setattr(orchestrator, "enqueue", spy_enqueue)
    return calls
