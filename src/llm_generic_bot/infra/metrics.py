from __future__ import annotations

# LEGACY_METRICS_SPLIT_CHECKLIST
# - [x] Snapshot dataclasses extracted to metrics_snapshot.py
# - [x] Service layer moved to metrics_service.py
# - [ ] Legacy module-level state replaced with structured backend

from threading import Lock
from typing import Dict, Mapping, MutableMapping, Tuple

from .metrics_service import (
    InMemoryMetricsService,
    MetricsRecorder,
    MetricsService,
    NullMetricsRecorder,
    WeeklyMetricsSnapshot,
    collect_weekly_snapshot,
    make_metrics_recorder,
    utcnow,
)
from .metrics_snapshot import CounterSnapshot, ObservationSnapshot

__all__ = [
    "CounterSnapshot",
    "InMemoryMetricsService",
    "MetricsRecorder",
    "MetricsService",
    "NullMetricsRecorder",
    "ObservationSnapshot",
    "WeeklyMetricsSnapshot",
    "collect_weekly_snapshot",
    "configure_backend",
    "report_permit_denied",
    "report_send_failure",
    "report_send_success",
    "weekly_snapshot",
    "reset_for_test",
]


_lock = Lock()
_NOOP_BACKEND = NullMetricsRecorder()
_backend: MetricsRecorder = _NOOP_BACKEND
_backend_configured = False
_success: Dict[str, int] = {}
_failure: Dict[str, int] = {}
_histogram: Dict[str, MutableMapping[str, int]] = {}
_denials: list[Dict[str, str]] = []
_LATENCY_BUCKETS: Tuple[Tuple[float, str], ...] = (
    (1.0, "1s"),
    (3.0, "3s"),
    (float("inf"), ">3s"),
)


def configure_backend(recorder: MetricsRecorder | None) -> None:
    global _backend, _backend_configured
    configured = recorder is not None
    backend: MetricsRecorder
    if recorder is None:
        backend = _NOOP_BACKEND
    elif isinstance(recorder, MetricsService):
        backend = make_metrics_recorder(recorder)
    else:
        backend = recorder
    with _lock:
        _backend = backend
        _backend_configured = configured


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


def weekly_snapshot() -> dict[str, object]:
    generated_at = utcnow().isoformat()
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


def reset_for_test() -> None:
    global _backend, _backend_configured
    with _lock:
        _backend = _NOOP_BACKEND
        _backend_configured = False
        for store in (_success, _failure, _histogram, _denials):
            store.clear()
