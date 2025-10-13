from __future__ import annotations
# mypy: ignore-errors

import inspect
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable, Dict, List, Mapping, Protocol, Tuple

TagsKey = Tuple[Tuple[str, str], ...]
MetricKind = str


def _normalize_tags(tags: Mapping[str, str] | None) -> TagsKey:
    if not tags:
        return ()
    return tuple(sorted(tags.items()))


def _utcnow() -> datetime:
    return datetime.fromtimestamp(time.time(), timezone.utc)


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


class NullMetricsRecorder(MetricsRecorder):
    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        return None

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        return None


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

    def collect_weekly_snapshot(self, now: datetime | None = None) -> WeeklyMetricsSnapshot:
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
    """Backward compatible alias for the default in-memory metrics backend."""


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


_lock = Lock()
_backend: MetricsRecorder = NullMetricsRecorder()
_backend_configured = False
_success: Dict[str, int] = {}
_failure: Dict[str, int] = {}
_histogram: Dict[str, Dict[str, int]] = {}
_denials: List[Dict[str, str]] = []
_LATENCY_BUCKETS: Tuple[Tuple[float, str], ...] = (
    (1.0, "1s"),
    (3.0, "3s"),
    (float("inf"), ">3s"),
)


def configure_backend(recorder: MetricsService | MetricsRecorder) -> None:
    global _backend, _backend_configured
    backend: MetricsRecorder
    if isinstance(recorder, MetricsService):
        backend = make_metrics_recorder(recorder)
    else:
        backend = recorder
    with _lock:
        _backend = backend
        _backend_configured = True


async def report_send_success(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    base_tags = _base_tags(job, platform, channel)
    tags = _merge_tags(base_tags, permit_tags)
    duration_tags = {**base_tags, "unit": "seconds"}
    with _lock:
        backend = _backend
        configured = _backend_configured
        if configured:
            _success[job] = _success.get(job, 0) + 1
            _record_latency(job, duration_seconds)
    backend.increment("send.success", tags=tags)
    backend.observe("send.duration", duration_seconds, tags=duration_tags)


async def report_send_failure(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    error_type: str,
) -> None:
    base_tags = _base_tags(job, platform, channel)
    increment_tags = dict(base_tags)
    increment_tags["error"] = error_type
    duration_tags = {**base_tags, "unit": "seconds"}
    with _lock:
        backend = _backend
        configured = _backend_configured
        if configured:
            _failure[job] = _failure.get(job, 0) + 1
            _record_latency(job, duration_seconds)
    backend.increment("send.failure", tags=increment_tags)
    backend.observe("send.duration", duration_seconds, tags=duration_tags)


def report_permit_denied(
    *,
    job: str,
    platform: str,
    channel: str | None,
    reason: str,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    base_tags = _base_tags(job, platform, channel)
    tags = _merge_tags(base_tags, permit_tags)
    tags["reason"] = reason
    with _lock:
        backend = _backend
        if _backend_configured:
            _denials.append(dict(tags))
    backend.increment("send.denied", tags=tags)


def weekly_snapshot() -> Mapping[str, object]:
    generated_at = _utcnow().isoformat()
    with _lock:
        success = dict(_success)
        failure = dict(_failure)
        histogram = {job: dict(buckets) for job, buckets in _histogram.items()}
        denials = [dict(item) for item in _denials]
    success_rate: Dict[str, Dict[str, float]] = {}
    for job in sorted(set(success) | set(failure)):
        success_count = success.get(job, 0)
        failure_count = failure.get(job, 0)
        total = success_count + failure_count
        if total == 0:
            continue
        success_rate[job] = {
            "success": success_count,
            "failure": failure_count,
            "ratio": success_count / total,
        }
    return {
        "generated_at": generated_at,
        "success_rate": success_rate,
        "latency_histogram_seconds": histogram,
        "permit_denials": denials,
    }


def _base_tags(job: str, platform: str, channel: str | None) -> Dict[str, str]:
    return {
        "job": job,
        "platform": platform,
        "channel": channel or "-",
    }


def _merge_tags(
    base_tags: Mapping[str, str],
    permit_tags: Mapping[str, str] | None,
) -> Dict[str, str]:
    tags = dict(base_tags)
    if permit_tags:
        tags.update(dict(permit_tags))
    return tags


def _record_latency(job: str, value: float) -> None:
    bucket = _select_bucket(value)
    job_hist = _histogram.get(job)
    if job_hist is None:
        job_hist = {}
        _histogram[job] = job_hist
    job_hist[bucket] = job_hist.get(bucket, 0) + 1


def _select_bucket(value: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if value <= threshold:
            return label
    return _LATENCY_BUCKETS[-1][1]


def _materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> Dict[str, Dict[TagsKey, CounterSnapshot]]:
    materialized: Dict[str, Dict[TagsKey, CounterSnapshot]] = {}
    for name, series in data.items():
        counters: Dict[TagsKey, CounterSnapshot] = {}
        for tags, count in series.items():
            counters[tags] = CounterSnapshot(count=count)
        materialized[name] = counters
    return materialized


def _materialize_observations(
    data: Mapping[str, Mapping[TagsKey, List[float]]]
) -> Dict[str, Dict[TagsKey, ObservationSnapshot]]:
    materialized: Dict[str, Dict[TagsKey, ObservationSnapshot]] = {}
    for name, series in data.items():
        observations: Dict[TagsKey, ObservationSnapshot] = {}
        for tags, values in series.items():
            if not values:
                continue
            total = float(sum(values))
            count = len(values)
            observations[tags] = ObservationSnapshot(
                count=count,
                minimum=min(values),
                maximum=max(values),
                total=total,
                average=total / count,
            )
        materialized[name] = observations
    return materialized


def reset_for_test() -> None:
    global _backend, _backend_configured
    with _lock:
        _backend = NullMetricsRecorder()
        _backend_configured = False
        for store in (_success, _failure, _histogram, _denials):
            store.clear()
