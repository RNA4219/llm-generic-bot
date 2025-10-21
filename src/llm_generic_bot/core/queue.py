from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True, slots=True)
class QueueBatch:
    priority: int
    text: str
    channel: Optional[str]
    job: str
    created_at: float
    batch_id: str


@dataclass(slots=True)
class _PendingBatch:
    start: float
    job: str
    messages: List[str] = field(default_factory=list)
    priority: int = 0
    channel: Optional[str] = None
    ready_at: float = 0.0
    force_ready: bool = False
    batch_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(slots=True)
class _BatchRecord:
    job: str
    channel: Optional[str]
    last_seen: float
    holds: Dict[str, float] = field(default_factory=dict)

    def expire(self, now: float) -> None:
        expired = [level for level, until in self.holds.items() if now >= until]
        for level in expired:
            self.holds.pop(level, None)

    def note_seen(self, ts: float) -> None:
        if ts > self.last_seen:
            self.last_seen = ts


class CoalesceQueue:
    """Merge nearby messages into priority-aware batches.

    Priorities use lower integers to represent higher urgency.
    """

    def __init__(self, window_seconds: float, threshold: int) -> None:
        self._window = window_seconds
        self._threshold = threshold
        self._pending: List[_PendingBatch] = []
        self._index: Dict[str, _PendingBatch] = {}
        self._ledger: OrderedDict[str, _BatchRecord] = OrderedDict()
        self._recent_limit = 1024

    @property
    def window_seconds(self) -> float:
        return self._window

    def push(
        self,
        text: str,
        *,
        priority: int,
        job: str,
        created_at: Optional[float] = None,
        channel: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        ts = created_at if created_at is not None else time.time()
        if batch_id is not None and self._should_skip(batch_id, ts, job, channel):
            return
        batch = self._find_batch(ts, channel, job, priority, batch_id)
        if batch is None:
            resolved_id = batch_id or uuid.uuid4().hex
            batch = _PendingBatch(
                start=ts,
                job=job,
                priority=priority,
                channel=channel,
                ready_at=ts + self._window,
                batch_id=resolved_id,
            )
            self._pending.append(batch)
            self._index[batch.batch_id] = batch
        else:
            batch.priority = min(batch.priority, priority)
            if batch_id is not None and batch.batch_id == batch_id:
                batch.messages = []
        if batch_id is not None and batch.batch_id == batch_id:
            batch.start = min(batch.start, ts)
            batch.channel = channel
            batch.messages = [text]
            batch.ready_at = ts + self._window
            batch.force_ready = False
        else:
            batch.messages.append(text)
            if len(batch.messages) >= self._threshold:
                batch.force_ready = True
                batch.ready_at = min(batch.ready_at, ts)
        self._remember(batch.batch_id, ts, job=batch.job, channel=batch.channel)

    def pop_ready(self, now: float) -> List[QueueBatch]:
        ready: List[QueueBatch] = []
        remaining: List[_PendingBatch] = []
        for batch in self._pending:
            if batch.force_ready or now >= batch.ready_at:
                if len(batch.messages) == 1:
                    text_obj = batch.messages[0]
                else:
                    text_obj = "\n".join(str(message) for message in batch.messages)
                ready.append(
                    QueueBatch(
                        priority=batch.priority,
                        text=text_obj,
                        channel=batch.channel,
                        job=batch.job,
                        created_at=batch.start,
                        batch_id=batch.batch_id,
                    )
                )
                self._index.pop(batch.batch_id, None)
            else:
                remaining.append(batch)
        self._pending = remaining
        ready.sort(key=lambda item: (item.priority, item.created_at))
        return ready

    def _find_batch(
        self,
        ts: float,
        channel: Optional[str],
        job: str,
        priority: int,
        batch_id: Optional[str] = None,
    ) -> Optional[_PendingBatch]:
        if batch_id is not None:
            existing = self._index.get(batch_id)
            if existing is not None:
                return existing
        for batch in self._pending:
            if batch.channel != channel or batch.job != job:
                continue
            if priority > batch.priority:
                continue
            if ts - batch.start <= self._window:
                self._index[batch.batch_id] = batch
                return batch
        return None

    def _should_skip(
        self,
        batch_id: str,
        ts: float,
        job: str,
        channel: Optional[str],
    ) -> bool:
        record = self._ledger.get(batch_id)
        if record is None:
            return False
        record.expire(ts)
        if record.job != job:
            return True
        if channel is not None and record.channel not in (None, channel):
            return True
        if record.channel is None and channel is not None:
            record.channel = channel
        if record.holds:
            hold_until = max(record.holds.values())
            if ts < hold_until:
                return True
        return ts <= record.last_seen

    def _remember(
        self,
        batch_id: str,
        ts: float,
        *,
        job: str,
        channel: Optional[str],
    ) -> None:
        record = self._ledger.get(batch_id)
        if record is None:
            record = _BatchRecord(job=job, channel=channel, last_seen=ts)
            self._ledger[batch_id] = record
        else:
            if record.job != job:
                record.job = job
            if record.channel is None and channel is not None:
                record.channel = channel
            record.expire(ts)
            record.note_seen(ts)
        self._ledger.move_to_end(batch_id)
        while len(self._ledger) > self._recent_limit:
            self._ledger.popitem(last=False)

    def mark_reevaluation_pending(
        self,
        batch_id: str,
        *,
        job: str,
        channel: Optional[str],
        level: str,
        until: float,
    ) -> None:
        if not level:
            raise ValueError("reevaluation level must be non-empty")
        record = self._ledger.get(batch_id)
        if record is None:
            record = _BatchRecord(job=job, channel=channel, last_seen=until)
            self._ledger[batch_id] = record
        else:
            if record.job != job:
                return
            if channel is not None and record.channel not in (None, channel):
                return
            if record.channel is None and channel is not None:
                record.channel = channel
            record.expire(until)
            record.note_seen(until)
        record.holds[level] = until
        self._ledger.move_to_end(batch_id)
        while len(self._ledger) > self._recent_limit:
            self._ledger.popitem(last=False)
