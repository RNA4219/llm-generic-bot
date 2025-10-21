from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Mapping

from .aggregator_records import (
    _MetricIncrementCall,
    _MetricObservationCall,
    _MetricsHistory,
    _PermitDenialRecord,
    _SendEventRecord,
    _normalize_retention_days,
    _prepare_permit_denial,
    _prepare_send_delay,
    _prepare_send_failure,
    _prepare_send_success,
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
    retention_days: int = _DEFAULT_RETENTION_DAYS
    _history: _MetricsHistory = field(default_factory=_MetricsHistory)

    @property
    def _send_events(self) -> list[_SendEventRecord]:
        return self._history.send_events

    @_send_events.setter
    def _send_events(self, value: list[_SendEventRecord]) -> None:
        self._history.send_events = value

    @property
    def _permit_denials(self) -> list[_PermitDenialRecord]:
        return self._history.permit_denials

    @_permit_denials.setter
    def _permit_denials(self, value: list[_PermitDenialRecord]) -> None:
        self._history.permit_denials = value

    def configure_backend(self, recorder: MetricsRecorder | None) -> None:
        backend, configured = _resolve_backend(recorder)
        with self.lock:
            self.backend = backend
            self.backend_configured = configured

    def clear_history(self) -> None:
        with self.lock:
            self._history.clear()

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
        record, increment_call, observation_call = _prepare_send_success(
            recorded_at=_utcnow(),
            job=job,
            platform=platform,
            channel=channel,
            duration_seconds=duration_seconds,
            permit_tags=permit_tags,
        )
        backend = self._record_history(record)
        self._apply_increment(backend, increment_call)
        self._apply_observation(backend, observation_call)

    def report_send_failure(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        duration_seconds: float,
        error_type: str,
    ) -> None:
        record, increment_call, observation_call = _prepare_send_failure(
            recorded_at=_utcnow(),
            job=job,
            platform=platform,
            channel=channel,
            duration_seconds=duration_seconds,
            error_type=error_type,
        )
        backend = self._record_history(record)
        self._apply_increment(backend, increment_call)
        self._apply_observation(backend, observation_call)

    def report_permit_denied(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        reason: str,
        permit_tags: Mapping[str, str] | None,
    ) -> None:
        record, increment_call = _prepare_permit_denial(
            recorded_at=_utcnow(),
            job=job,
            platform=platform,
            channel=channel,
            reason=reason,
            permit_tags=permit_tags,
        )
        backend = self._record_history(record)
        self._apply_increment(backend, increment_call)

    def report_send_delay(
        self,
        *,
        job: str,
        platform: str,
        channel: str | None,
        delay_seconds: float,
    ) -> None:
        observation_call = _prepare_send_delay(
            job=job,
            platform=platform,
            channel=channel,
            delay_seconds=delay_seconds,
        )
        backend = self._backend_for_delay()
        self._apply_observation(backend, observation_call)

    def weekly_snapshot(self) -> dict[str, object]:
        generated_at = _utcnow()
        with self.lock:
            snapshot = self._history.trim_and_build_snapshot(
                generated_at=generated_at,
                retention_days=self.retention_days,
            )
        return snapshot

    def reset(self) -> None:
        with self.lock:
            self.backend = _NOOP_BACKEND
            self.backend_configured = False
            self._history = _MetricsHistory()
            self.retention_days = _DEFAULT_RETENTION_DAYS

    def _record_history(
        self, record: _SendEventRecord | _PermitDenialRecord
    ) -> MetricsRecorder:
        with self.lock:
            backend = self.backend
            if self.backend_configured:
                self._history.store(record)
        return backend

    def _backend_for_delay(self) -> MetricsRecorder:
        with self.lock:
            return self.backend

    @staticmethod
    def _apply_increment(
        backend: MetricsRecorder, call: _MetricIncrementCall
    ) -> None:
        backend.increment(call.name, tags=call.tags)

    @staticmethod
    def _apply_observation(
        backend: MetricsRecorder, call: _MetricObservationCall
    ) -> None:
        backend.observe(call.name, call.value, tags=call.tags)

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
