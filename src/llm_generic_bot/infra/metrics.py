from __future__ import annotations

import inspect
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Protocol, Tuple

TagsKey = Tuple[Tuple[str, str], ...]
MetricKind = str


def _normalize_tags(tags: Mapping[str, str] | None) -> TagsKey:
    if not tags:
        return ()
    return tuple(sorted(tags.items()))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CounterSnapshot:
    count: int


@dataclass(frozen=True)
class ObservationSnapshot:
    count: int
    minimum: float
    maximum: float
    total: float
    average: float


@dataclass(frozen=True)
class WeeklyMetricsSnapshot:
    start: datetime
    end: datetime
    counters: Mapping[str, Mapping[TagsKey, CounterSnapshot]]
    observations: Mapping[str, Mapping[TagsKey, ObservationSnapshot]]

    @classmethod
    def empty(cls, *, now: datetime | None = None) -> "WeeklyMetricsSnapshot":
        reference = now or datetime.now(timezone.utc)
        return cls(start=reference, end=reference, counters={}, observations={})


@dataclass(frozen=True)
class _MetricRecord:
    name: str
    recorded_at: datetime
    tags: TagsKey
    kind: MetricKind
    value: float


class MetricsRecorder(Protocol):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        ...

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        ...


class MetricsService(MetricsRecorder):
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._records: List[_MetricRecord] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._store(name, 1.0, tags, "increment")

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._store(name, float(value), tags, "observe")

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if measurements:
            value = next(iter(measurements.values()))
            self.observe(name, float(value), tags=tags)
            return
        self.increment(name, tags=tags)

    def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> WeeklyMetricsSnapshot | Awaitable[WeeklyMetricsSnapshot]:
        reference = now or self._clock()
        start = reference - timedelta(days=7)
        with self._lock:
            relevant = [r for r in self._records if start <= r.recorded_at <= reference]
            self._records = [r for r in self._records if r.recorded_at >= start]
        counters: Dict[str, Dict[TagsKey, int]] = {}
        observations: Dict[str, Dict[TagsKey, List[float]]] = {}
        for record in relevant:
            if record.kind == "increment":
                counter_metric = counters.get(record.name)
                if counter_metric is None:
                    counter_metric = {}
                    counters[record.name] = counter_metric
                counter_metric[record.tags] = counter_metric.get(record.tags, 0) + 1
            elif record.kind == "observe":
                observation_metric = observations.get(record.name)
                if observation_metric is None:
                    observation_metric = {}
                    observations[record.name] = observation_metric
                value_list = observation_metric.get(record.tags)
                if value_list is None:
                    value_list = []
                    observation_metric[record.tags] = value_list
                value_list.append(record.value)
        return WeeklyMetricsSnapshot(
            start=start,
            end=reference,
            counters=_materialize_counters(counters),
            observations=_materialize_observations(observations),
        )

    def _store(
        self,
        name: str,
        value: float,
        tags: Mapping[str, str] | None,
        kind: MetricKind,
    ) -> None:
        record = _MetricRecord(
            name=name,
            recorded_at=self._clock(),
            tags=_normalize_tags(tags),
            kind=kind,
            value=value,
        )
        with self._lock:
            self._records.append(record)


class InMemoryMetricsService(MetricsService):
    async def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> WeeklyMetricsSnapshot:
        result = super().collect_weekly_snapshot(now)
        if inspect.isawaitable(result):
            return await result
        return result


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags, measurements={"value": value})


def make_metrics_recorder(service: MetricsService) -> _MetricsRecorderAdapter:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        return WeeklyMetricsSnapshot.empty()
    result = metrics.collect_weekly_snapshot()
    if inspect.isawaitable(result):
        return await result
    return result

def _materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> Dict[str, Dict[TagsKey, CounterSnapshot]]:
    return {
        name: {tags: CounterSnapshot(count=value) for tags, value in entries.items()}
        for name, entries in data.items()
    }


def _materialize_observations(
    data: Mapping[str, Mapping[TagsKey, List[float]]]
) -> Dict[str, Dict[TagsKey, ObservationSnapshot]]:
    result: Dict[str, Dict[TagsKey, ObservationSnapshot]] = {}
    for name, entries in data.items():
        snapshots = {}
        for tags, values in entries.items():
            if not values:
                continue
            total = sum(values)
            count = len(values)
            snapshots[tags] = ObservationSnapshot(
                count=count,
                minimum=min(values),
                maximum=max(values),
                total=total,
                average=total / count,
            )
        if snapshots:
            result[name] = snapshots
    return result


class NullMetricsRecorder(MetricsRecorder):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(
        self, name: str, value: float, tags: Mapping[str, str] | None = None
    ) -> None:
        return None


_lock = Lock()
_NULL_BACKEND = NullMetricsRecorder()
_backend: MetricsRecorder = _NULL_BACKEND
_totals: defaultdict[str, Counter[str]] = defaultdict(Counter)
_histogram: defaultdict[str, Counter[str]] = defaultdict(Counter)
_denials: List[Dict[str, str]] = []

_LATENCY_BUCKETS: tuple[tuple[float, str], ...] = (
    (1.0, "1s"),
    (3.0, "3s"),
    (10.0, "10s"),
    (30.0, "30s"),
    (float("inf"), ">30s"),
)


def configure_backend(recorder: MetricsRecorder) -> None:
    global _backend
    with _lock:
        _backend = recorder


def _bucket_latency(value: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if value <= threshold:
            return label
    return ">30s"


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.fromtimestamp(time.time(), tz=timezone.utc)


def _base_tags(
    job: str, platform: str, channel: str | None, extra: Mapping[str, str] | None = None
) -> Dict[str, str]:
    tags: Dict[str, str] = {
        "job": job,
        "platform": platform,
        "channel": channel or "-",
    }
    if extra:
        tags.update(extra)
    return tags


def _record_outcome(job: str, outcome: str, duration: float) -> None:
    if _backend is _NULL_BACKEND:
        return
    with _lock:
        _totals[job][outcome] += 1
        _histogram[job][_bucket_latency(duration)] += 1


def _record_send(
    outcome: str,
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    extra_tags: Mapping[str, str] | None,
) -> None:
    base = _base_tags(job, platform, channel, None)
    tags = dict(base)
    if extra_tags:
        tags.update(extra_tags)
    metric = "send.success" if outcome == "success" else "send.failure"
    _backend.increment(metric, tags=tags)
    _backend.observe("send.duration", duration_seconds, tags={**base, "unit": "seconds"})
    _record_outcome(job, outcome, duration_seconds)


async def report_send_success(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    _record_send(
        "success",
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        extra_tags=permit_tags,
    )


async def report_send_failure(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    error_type: str,
) -> None:
    _record_send(
        "failure",
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        extra_tags={"error": error_type},
    )


def report_permit_denied(
    *,
    job: str,
    platform: str,
    channel: str | None,
    reason: str,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    tags = _base_tags(job, platform, channel, {"reason": reason, **(permit_tags or {})})
    _backend.increment("send.denied", tags=tags)
    if _backend is _NULL_BACKEND:
        return
    with _lock:
        _denials.append(dict(tags))


def weekly_snapshot(*, now: datetime | None = None) -> Dict[str, Any]:
    reference = _now(now)
    with _lock:
        totals = {job: Counter(counter) for job, counter in _totals.items()}
        histogram = {job: dict(counter) for job, counter in _histogram.items()}
        denials = [dict(item) for item in _denials]
    success_rate = {
        job: {
            "success": counts.get("success", 0),
            "failure": counts.get("failure", 0),
            "ratio": (counts.get("success", 0) / total)
            if (total := counts.get("success", 0) + counts.get("failure", 0))
            else 0.0,
        }
        for job, counts in totals.items()
    }
    return {
        "generated_at": reference.isoformat(),
        "success_rate": success_rate,
        "latency_histogram_seconds": histogram,
        "permit_denials": denials,
    }


def reset_for_test() -> None:
    global _backend
    with _lock:
        _backend = _NULL_BACKEND
        _totals.clear()
        _histogram.clear()
        _denials.clear()
