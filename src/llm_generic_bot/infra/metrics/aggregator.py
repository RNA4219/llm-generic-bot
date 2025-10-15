from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Mapping

from .service import (
    MetricsRecorder,
    MetricsService,
    _DEFAULT_RETENTION_DAYS,
    _NOOP_BACKEND,
    _utcnow as _service_utcnow,
    make_metrics_recorder,
)


def _utcnow() -> datetime:
    return _service_utcnow()


@dataclass(frozen=True)
class _SendEventRecord:
    recorded_at: datetime
    job: str
    outcome: str
    duration: float


@dataclass(frozen=True)
class _PermitDenialRecord:
    recorded_at: datetime
    payload: dict[str, str]


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
    retention_days: int = _DEFAULT_RETENTION_DAYS

    def configure_backend(self, recorder: MetricsRecorder | None) -> None:
        backend, configured = self._resolve_backend(recorder)
        with self.lock:
            self.backend = backend
            self.backend_configured = configured

    def set_retention_days(self, retention_days: int | None) -> None:
        value = (
            _DEFAULT_RETENTION_DAYS if retention_days is None else max(1, retention_days)
        )
        with self.lock:
            self.retention_days = value

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
        with self.lock:
            retention_days = self.retention_days
        cutoff = generated_at - timedelta(days=retention_days)
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
            self.retention_days = _DEFAULT_RETENTION_DAYS

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


def set_retention_days(retention_days: int | None) -> None:
    _AGGREGATOR.set_retention_days(retention_days)


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


def reset_for_test() -> None:
    _AGGREGATOR.reset()


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


__all__ = [
    "configure_backend",
    "report_permit_denied",
    "report_send_failure",
    "report_send_success",
    "reset_for_test",
    "set_retention_days",
    "weekly_snapshot",
]
