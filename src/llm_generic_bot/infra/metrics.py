from __future__ import annotations

# LEGACY_METRICS_SPLIT_CHECKLIST
# - [x] Extracted service primitives into reusable classes
# - [ ] Replace module-level global aggregator with injectable counterpart
# - [ ] Remove legacy global wrappers once call sites migrate

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal, Protocol

TagsKey = tuple[tuple[str, str], ...]
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
    def empty(cls, *, now: datetime | None = None) -> WeeklyMetricsSnapshot:
        reference = now or _utcnow()
        return cls(start=reference, end=reference, counters={}, observations={})


SnapshotResult = WeeklyMetricsSnapshot | Awaitable[WeeklyMetricsSnapshot]


@dataclass(frozen=True)
class _MetricRecord:
    name: str
    recorded_at: datetime
    tags: TagsKey
    kind: MetricKind
    value: float


@dataclass(frozen=True)
class _SendEventRecord:
    recorded_at: datetime
    job: str
    outcome: Literal["success", "failure"]
    duration: float


@dataclass(frozen=True)
class _PermitDenialRecord:
    recorded_at: datetime
    payload: dict[str, str]


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


_NOOP_BACKEND = NullMetricsRecorder()


class MetricsService(MetricsRecorder):
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        retention_days: int = 7,
    ) -> None:
        self._clock = clock or _utcnow
        self._lock = Lock()
        self._records: list[_MetricRecord] = []
        self._retention_days = max(1, retention_days)

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
        _ = metadata
        if measurements:
            value = next(iter(measurements.values()))
            self.observe(name, float(value), tags=tags)
            return
        self.increment(name, tags=tags)

    def collect_weekly_snapshot(
        self, now: datetime | None = None
    ) -> SnapshotResult:
        reference = now or self._clock()
        start = reference - timedelta(days=self._retention_days)
        with self._lock:
            relevant = [
                record
                for record in self._records
                if start <= record.recorded_at <= reference
            ]
            self._records = [
                record for record in self._records if record.recorded_at >= start
            ]
        counters: dict[str, dict[TagsKey, int]] = {}
        observations: dict[str, dict[TagsKey, list[float]]] = {}
        for record in relevant:
            if record.kind == "increment":
                counter_metric = counters.setdefault(record.name, {})
                counter_metric[record.tags] = counter_metric.get(record.tags, 0) + 1
            elif record.kind == "observe":
                observation_metric = observations.setdefault(record.name, {})
                values = observation_metric.setdefault(record.tags, [])
                values.append(record.value)
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
        result = super().collect_weekly_snapshot(now=now)
        if isinstance(result, Awaitable):
            return await result
        return result


class _MetricsRecorderAdapter:
    __slots__ = ("_service",)

    def __init__(self, service: MetricsService) -> None:
        self._service = service

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self._service.record_event(name, tags=tags)

    def observe(
        self, name: str, value: float, tags: Mapping[str, str] | None = None
    ) -> None:
        self._service.record_event(
            name, tags=tags, measurements={"value": float(value)}
        )


def make_metrics_recorder(service: MetricsService) -> MetricsRecorder:
    return _MetricsRecorderAdapter(service)


async def collect_weekly_snapshot(
    metrics: MetricsService | None,
) -> WeeklyMetricsSnapshot:
    if metrics is None:
        return WeeklyMetricsSnapshot.empty()
    result = metrics.collect_weekly_snapshot()
    if isinstance(result, Awaitable):
        return await result
    return result


_LATENCY_BUCKETS: tuple[tuple[float, str], ...] = (
    (1.0, "1s"),
    (3.0, "3s"),
    (float("inf"), ">3s"),
)


@dataclass
class _GlobalMetricsAggregator:
    lock: Lock = field(default_factory=Lock)
    backend: MetricsRecorder = field(default_factory=lambda: _NOOP_BACKEND)
    backend_configured: bool = False
    _send_events: list[_SendEventRecord] = field(default_factory=list)
    _permit_denials: list[_PermitDenialRecord] = field(default_factory=list)

    def configure_backend(self, recorder: MetricsRecorder | None) -> None:
        backend, configured = self._resolve_backend(recorder)
        with self.lock:
            self.backend = backend
            self.backend_configured = configured

    def report_send_success(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        duration_seconds: float,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        base_tags = _base_tags(job, platform, channel)
        tags = _merge_tags(base_tags, permit_tags)
        duration_tags = {**base_tags, "unit": "seconds"}
        with self.lock:
            backend = self.backend
            configured = self.backend_configured
            if configured:
                self._send_events.append(
                    _SendEventRecord(
                        recorded_at=_utcnow(),
                        job=job,
                        outcome="success",
                        duration=float(duration_seconds),
                    )
                )
        backend.increment("send.success", tags=tags)
        backend.observe(
            "send.duration", duration_seconds, tags=duration_tags
        )

    def report_send_failure(
        self,
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
        with self.lock:
            backend = self.backend
            configured = self.backend_configured
            if configured:
                self._send_events.append(
                    _SendEventRecord(
                        recorded_at=_utcnow(),
                        job=job,
                        outcome="failure",
                        duration=float(duration_seconds),
                    )
                )
        backend.increment("send.failure", tags=increment_tags)
        backend.observe(
            "send.duration", duration_seconds, tags=duration_tags
        )

    def report_permit_denied(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        reason: str,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        base_tags = _base_tags(job, platform, channel)
        tags = _merge_tags(base_tags, permit_tags)
        tags["reason"] = reason
        with self.lock:
            backend = self.backend
            configured = self.backend_configured
            if configured:
                self._permit_denials.append(
                    _PermitDenialRecord(
                        recorded_at=_utcnow(), payload=dict(tags)
                    )
                )
        backend.increment("send.denied", tags=tags)

    def weekly_snapshot(self) -> dict[str, object]:
        generated_at = _utcnow()
        cutoff = generated_at - timedelta(days=7)
        with self.lock:
            send_events = [
                record
                for record in self._send_events
                if record.recorded_at >= cutoff
            ]
            permit_denials = [
                record
                for record in self._permit_denials
                if record.recorded_at >= cutoff
            ]
            self._send_events = send_events
            self._permit_denials = permit_denials
        success: dict[str, int] = {}
        failure: dict[str, int] = {}
        histogram: dict[str, dict[str, int]] = {}
        for record in send_events:
            buckets = histogram.setdefault(record.job, {})
            bucket = _select_bucket(record.duration)
            buckets[bucket] = buckets.get(bucket, 0) + 1
            if record.outcome == "success":
                success[record.job] = success.get(record.job, 0) + 1
            else:
                failure[record.job] = failure.get(record.job, 0) + 1
        success_rate: dict[str, dict[str, float | int]] = {}
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
            "generated_at": generated_at.isoformat(),
            "success_rate": success_rate,
            "latency_histogram_seconds": histogram,
            "permit_denials": [dict(record.payload) for record in permit_denials],
        }

    def reset(self) -> None:
        with self.lock:
            self.backend = _NOOP_BACKEND
            self.backend_configured = False
            self._send_events.clear()
            self._permit_denials.clear()

    @staticmethod
    def _resolve_backend(
        recorder: MetricsRecorder | None,
    ) -> tuple[MetricsRecorder, bool]:
        if recorder is None:
            return _NOOP_BACKEND, False
        if isinstance(recorder, MetricsService):
            return make_metrics_recorder(recorder), True
        return recorder, True


_AGGREGATOR = _GlobalMetricsAggregator()


def configure_backend(recorder: MetricsRecorder | None) -> None:
    _AGGREGATOR.configure_backend(recorder)


async def report_send_success(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    _AGGREGATOR.report_send_success(
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        permit_tags=permit_tags,
    )


async def report_send_failure(
    *,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    error_type: str,
) -> None:
    _AGGREGATOR.report_send_failure(
        job=job,
        platform=platform,
        channel=channel,
        duration_seconds=duration_seconds,
        error_type=error_type,
    )


def report_permit_denied(
    *,
    job: str,
    platform: str,
    channel: str | None,
    reason: str,
    permit_tags: Mapping[str, str] | None = None,
) -> None:
    _AGGREGATOR.report_permit_denied(
        job=job,
        platform=platform,
        channel=channel,
        reason=reason,
        permit_tags=permit_tags,
    )


def weekly_snapshot() -> dict[str, object]:
    return _AGGREGATOR.weekly_snapshot()


def _base_tags(job: str, platform: str, channel: str | None) -> dict[str, str]:
    return {
        "job": job,
        "platform": platform,
        "channel": channel or "-",
    }


def _merge_tags(
    base_tags: Mapping[str, str],
    permit_tags: Mapping[str, str] | None,
) -> dict[str, str]:
    tags = dict(base_tags)
    if permit_tags:
        tags.update(dict(permit_tags))
    return tags


def _select_bucket(value: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if value <= threshold:
            return label
    return _LATENCY_BUCKETS[-1][1]


def _materialize_counters(
    data: Mapping[str, Mapping[TagsKey, int]]
) -> dict[str, dict[TagsKey, CounterSnapshot]]:
    materialized: dict[str, dict[TagsKey, CounterSnapshot]] = {}
    for name, series in data.items():
        counters: dict[TagsKey, CounterSnapshot] = {}
        for tags, count in series.items():
            counters[tags] = CounterSnapshot(count=count)
        materialized[name] = counters
    return materialized


def _materialize_observations(
    data: Mapping[str, Mapping[TagsKey, list[float]]]
) -> dict[str, dict[TagsKey, ObservationSnapshot]]:
    materialized: dict[str, dict[TagsKey, ObservationSnapshot]] = {}
    for name, series in data.items():
        observations: dict[TagsKey, ObservationSnapshot] = {}
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
    _AGGREGATOR.reset()
