from __future__ import annotations

from collections import Counter, defaultdict
import datetime as dt
from threading import Lock
from typing import Dict, Mapping

from llm_generic_bot.core.orchestrator import MetricsRecorder, NullMetricsRecorder

_BUCKETS: tuple[tuple[float, str], ...] = ((1.0, "1s"), (3.0, "3s"), (10.0, "10s"), (float("inf"), "inf"))
_backend: MetricsRecorder = NullMetricsRecorder()
_backend_configured = False
_lock = Lock()
_success: Dict[str, int] = {}
_failure: Dict[str, int] = {}
_histogram: defaultdict[str, Counter[str]] = defaultdict(Counter)
_denials: list[dict[str, str]] = []


def configure_backend(recorder: MetricsRecorder | None) -> None:
    global _backend, _backend_configured
    with _lock:
        _backend = recorder or NullMetricsRecorder()
        _backend_configured = recorder is not None
        for store in (_success, _failure, _histogram, _denials):
            store.clear()


def _base_tags(job: str, platform: str, channel: str | None) -> dict[str, str]:
    return {"job": job, "platform": platform, "channel": channel or "-"}


def report_permit_denied(
    *, job: str, platform: str, channel: str | None, reason: str, permit_tags: Mapping[str, str] | None = None
) -> None:
    tags = {**_base_tags(job, platform, channel), "reason": reason, **(permit_tags or {})}
    _backend.increment("send.denied", tags)
    if _backend_configured:
        with _lock:
            _denials.append(tags.copy())


def _record(job: str, duration_seconds: float, *, success: bool) -> None:
    if not _backend_configured:
        return
    bucket = next(label for limit, label in _BUCKETS if duration_seconds <= limit)
    with _lock:
        _histogram[job][bucket] += 1
        counter = _success if success else _failure
        counter[job] = counter.get(job, 0) + 1


async def report_send_success(
    *, job: str, platform: str, channel: str | None, duration_seconds: float, permit_tags: Mapping[str, str] | None = None
) -> None:
    tags = _base_tags(job, platform, channel)
    _backend.increment("send.success", {**tags, **(permit_tags or {})})
    _record(job, duration_seconds, success=True)
    _backend.observe("send.duration", duration_seconds, {**tags, "unit": "seconds"})


async def report_send_failure(
    *, job: str, platform: str, channel: str | None, duration_seconds: float, error_type: str
) -> None:
    tags = _base_tags(job, platform, channel)
    _backend.increment("send.failure", {**tags, "error": error_type})
    _record(job, duration_seconds, success=False)
    _backend.observe("send.duration", duration_seconds, {**tags, "unit": "seconds"})


def weekly_snapshot() -> dict[str, object]:
    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    with _lock:
        jobs = sorted(set(_success) | set(_failure))
        success_rate = {}
        for job in jobs:
            s, f = _success.get(job, 0), _failure.get(job, 0)
            if s + f:
                success_rate[job] = {"success": s, "failure": f, "ratio": s / (s + f)}
        latency = {
            job: {label: counts[label] for _, label in _BUCKETS if counts[label] > 0}
            for job, counts in sorted(_histogram.items())
            if counts
        }
        denials = list(_denials)
    return {
        "generated_at": generated,
        "success_rate": success_rate,
        "latency_histogram_seconds": latency,
        "permit_denials": denials,
    }


def reset_for_test() -> None:
    global _backend, _backend_configured
    with _lock:
        _backend = NullMetricsRecorder()
        _backend_configured = False
        for store in (_success, _failure, _histogram, _denials):
            store.clear()
