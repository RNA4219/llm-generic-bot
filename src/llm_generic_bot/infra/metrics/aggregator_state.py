from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Mapping

from .aggregator_records import (
    _PermitDenialRecord,
    _SendEventRecord,
    _base_tags,
    _build_snapshot,
    _calculate_success_rate,
    _merge_tags,
    _normalize_retention_days,
    _retain_recent,
    _summarize_send_events,
)
from .service import (
    MetricsRecorder,
    MetricsService,
    _DEFAULT_RETENTION_DAYS,
    _NOOP_BACKEND,
    _utcnow as _service_utcnow,
    make_metrics_recorder,
)


def _utcnow() -> datetime:
    aggregator_module = sys.modules.get(
        "llm_generic_bot.infra.metrics.aggregator"
    )
    if aggregator_module is not None:
        candidate = getattr(aggregator_module, "_utcnow", None)
        if callable(candidate) and candidate is not _utcnow:
            return candidate()
    return _service_utcnow()


@dataclass
class _GlobalMetricsAggregator:
    lock: Lock = field(default_factory=Lock)
    backend: MetricsRecorder = field(default_factory=lambda: _NOOP_BACKEND)
    backend_configured: bool = False
    _send_events: list[_SendEventRecord] = field(default_factory=list)
    _permit_denials: list[_PermitDenialRecord] = field(default_factory=list)
    retention_days: int = _DEFAULT_RETENTION_DAYS

    def configure_backend(self, recorder: MetricsRecorder | None) -> None:
        backend, configured = _resolve_backend(recorder)
        with self.lock:
            self.backend = backend
            self.backend_configured = configured

    def clear_history(self) -> None:
        with self.lock:
            self._send_events.clear()
            self._permit_denials.clear()

    def set_retention_days(self, retention_days: int | None) -> None:
        value = _normalize_retention_days(retention_days)
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
        backend = self._backend_for_recording(
            _SendEventRecord(
                recorded_at=_utcnow(),
                job=job,
                outcome="success",
                duration=float(duration_seconds),
            )
        )
        backend.increment("send.success", tags=tags)
        backend.observe("send.duration", duration_seconds, tags=duration_tags)

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
        backend = self._backend_for_recording(
            _SendEventRecord(
                recorded_at=_utcnow(),
                job=job,
                outcome="failure",
                duration=float(duration_seconds),
            )
        )
        backend.increment("send.failure", tags=increment_tags)
        backend.observe("send.duration", duration_seconds, tags=duration_tags)

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
        backend = self._backend_for_recording(
            _PermitDenialRecord(recorded_at=_utcnow(), payload=dict(tags))
        )
        backend.increment("send.denied", tags=tags)

    def report_send_delay(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        delay_seconds: float,
    ) -> None:
        tags = _base_tags(job, platform, channel)
        observation_tags = {**tags, "unit": "seconds"}
        backend = self._backend_for_delay()
        backend.observe("send.delay_seconds", float(delay_seconds), tags=observation_tags)

    def weekly_snapshot(self) -> dict[str, object]:
        generated_at = _utcnow()
        cutoff = generated_at - timedelta(days=self._retention_days())
        with self.lock:
            send_events, permit_denials = self._trim_history(cutoff)
        success_counts, failure_counts, histogram = _summarize_send_events(send_events)
        success_rate = _calculate_success_rate(success_counts, failure_counts)
        return _build_snapshot(
            generated_at=generated_at,
            success_rate=success_rate,
            histogram=histogram,
            permit_denials=permit_denials,
        )

    def reset(self) -> None:
        with self.lock:
            self.backend = _NOOP_BACKEND
            self.backend_configured = False
            self._send_events.clear()
            self._permit_denials.clear()
            self.retention_days = _DEFAULT_RETENTION_DAYS

    def _backend_for_recording(
        self, record: _SendEventRecord | _PermitDenialRecord
    ) -> MetricsRecorder:
        with self.lock:
            backend = self.backend
            if self.backend_configured:
                if isinstance(record, _SendEventRecord):
                    self._send_events.append(record)
                else:
                    self._permit_denials.append(record)
        return backend

    def _backend_for_delay(self) -> MetricsRecorder:
        with self.lock:
            return self.backend

    def _trim_history(
        self, cutoff: datetime
    ) -> tuple[list[_SendEventRecord], list[_PermitDenialRecord]]:
        send_events = _retain_recent(self._send_events, cutoff)
        permit_denials = _retain_recent(self._permit_denials, cutoff)
        self._send_events = send_events
        self._permit_denials = permit_denials
        return send_events, permit_denials

    def _retention_days(self) -> int:
        with self.lock:
            return self.retention_days


def _resolve_backend(
    recorder: MetricsRecorder | None,
) -> tuple[MetricsRecorder, bool]:
    if recorder is None:
        return _NOOP_BACKEND, False
    if isinstance(recorder, MetricsService):
        return make_metrics_recorder(recorder), True
    return recorder, True


_AGGREGATOR = _GlobalMetricsAggregator()


def weekly_snapshot() -> dict[str, object]:
    return _AGGREGATOR.weekly_snapshot()


def reset_for_test() -> None:
    _AGGREGATOR.reset()
