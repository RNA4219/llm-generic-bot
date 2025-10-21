from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Mapping, Sequence

from .aggregator_records import (
    _MetricCall,
    _PermitDenialRecord,
    _SendEventRecord,
    _build_permit_denied_calls,
    _build_send_delay_calls,
    _build_send_failure_calls,
    _build_send_success_calls,
    _normalize_retention_days,
    _trim_and_build_snapshot,
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


def _emit_calls(backend: MetricsRecorder, calls: Sequence[_MetricCall]) -> None:
    for call in calls:
        call.apply(backend)


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
        record, calls = _build_send_success_calls(
            job=job,
            platform=platform,
            channel=channel,
            duration_seconds=duration_seconds,
            permit_tags=permit_tags,
            recorded_at=_utcnow(),
        )
        backend = self._backend_for_recording(record)
        _emit_calls(backend, calls)

    def report_send_failure(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        duration_seconds: float,
        error_type: str,
    ) -> None:
        record, calls = _build_send_failure_calls(
            job=job,
            platform=platform,
            channel=channel,
            duration_seconds=duration_seconds,
            error_type=error_type,
            recorded_at=_utcnow(),
        )
        backend = self._backend_for_recording(record)
        _emit_calls(backend, calls)

    def report_permit_denied(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        reason: str,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        record, calls = _build_permit_denied_calls(
            job=job,
            platform=platform,
            channel=channel,
            reason=reason,
            permit_tags=permit_tags,
            recorded_at=_utcnow(),
        )
        backend = self._backend_for_recording(record)
        _emit_calls(backend, calls)

    def report_send_delay(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        delay_seconds: float,
    ) -> None:
        backend = self._backend_for_delay()
        _emit_calls(backend, _build_send_delay_calls(
            job=job,
            platform=platform,
            channel=channel,
            delay_seconds=delay_seconds,
        ))

    def weekly_snapshot(self) -> dict[str, object]:
        generated_at = _utcnow()
        with self.lock:
            snapshot, send_events, permit_denials = _trim_and_build_snapshot(
                send_events=self._send_events,
                permit_denials=self._permit_denials,
                generated_at=generated_at,
                retention_days=self.retention_days,
            )
            self._send_events = send_events
            self._permit_denials = permit_denials
        return snapshot

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
