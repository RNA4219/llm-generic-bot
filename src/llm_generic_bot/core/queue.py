from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True, slots=True)
class QueueBatch:
    priority: int
    text: str
    channel: Optional[str]
    created_at: float


@dataclass(slots=True)
class _PendingBatch:
    start: float
    messages: List[str] = field(default_factory=list)
    priority: int = 0
    channel: Optional[str] = None
    ready_at: float = 0.0
    force_ready: bool = False


class CoalesceQueue:
    """Merge nearby messages into priority-aware batches.

    Priorities use lower integers to represent higher urgency.
    """

    def __init__(self, window_seconds: float, threshold: int) -> None:
        self._window = window_seconds
        self._threshold = threshold
        self._pending: List[_PendingBatch] = []

    @property
    def window_seconds(self) -> float:
        return self._window

    def push(
        self,
        text: str,
        *,
        priority: int,
        created_at: Optional[float] = None,
        channel: Optional[str] = None,
    ) -> None:
        ts = created_at if created_at is not None else time.time()
        batch = self._find_batch(ts, channel)
        if batch is None:
            batch = _PendingBatch(start=ts, priority=priority, channel=channel, ready_at=ts + self._window)
            self._pending.append(batch)
        else:
            batch.priority = min(batch.priority, priority)
        batch.messages.append(text)
        if len(batch.messages) >= self._threshold:
            batch.force_ready = True
            batch.ready_at = min(batch.ready_at, ts)

    def pop_ready(self, now: float) -> List[QueueBatch]:
        ready: List[QueueBatch] = []
        remaining: List[_PendingBatch] = []
        for batch in self._pending:
            if batch.force_ready or now >= batch.ready_at:
                ready.append(
                    QueueBatch(
                        priority=batch.priority,
                        text="\n".join(batch.messages),
                        channel=batch.channel,
                        created_at=batch.start,
                    )
                )
            else:
                remaining.append(batch)
        self._pending = remaining
        ready.sort(key=lambda item: (item.priority, item.created_at))
        return ready

    def _find_batch(self, ts: float, channel: Optional[str]) -> Optional[_PendingBatch]:
        for batch in self._pending:
            if batch.channel != channel:
                continue
            if ts - batch.start <= self._window:
                return batch
        return None
