from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Mapping, TypeVar

from .service import _DEFAULT_RETENTION_DAYS


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


@dataclass(frozen=True)
class _MetricIncrementCall:
    name: str
    tags: dict[str, str]


@dataclass(frozen=True)
class _MetricObservationCall:
    name: str
    value: float
    tags: dict[str, str]


@dataclass
class _MetricsHistory:
    _send_events: list[_SendEventRecord] = field(default_factory=list)
    _permit_denials: list[_PermitDenialRecord] = field(default_factory=list)

    @property
    def send_events(self) -> list[_SendEventRecord]:
        return self._send_events

    @send_events.setter
    def send_events(self, value: list[_SendEventRecord]) -> None:
        self._send_events = value

    @property
    def permit_denials(self) -> list[_PermitDenialRecord]:
        return self._permit_denials

    @permit_denials.setter
    def permit_denials(self, value: list[_PermitDenialRecord]) -> None:
        self._permit_denials = value

    def store(self, record: _SendEventRecord | _PermitDenialRecord) -> None:
        if isinstance(record, _SendEventRecord):
            self._send_events.append(record)
        else:
            self._permit_denials.append(record)

    def clear(self) -> None:
        self._send_events.clear()
        self._permit_denials.clear()

    def trim_and_build_snapshot(
        self,
        *,
        generated_at: datetime,
        retention_days: int,
    ) -> dict[str, object]:
        snapshot, send_events, permit_denials = _trim_and_build_snapshot(
            send_events=self._send_events,
            permit_denials=self._permit_denials,
            generated_at=generated_at,
            retention_days=retention_days,
        )
        self._send_events = send_events
        self._permit_denials = permit_denials
        return snapshot


_LATENCY_BUCKETS: tuple[tuple[float, str], ...] = (
    (1.0, "1s"),
    (3.0, "3s"),
    (float("inf"), ">3s"),
)


_RecordT = TypeVar("_RecordT", _SendEventRecord, _PermitDenialRecord)


def _normalize_retention_days(retention_days: int | None) -> int:
    return _DEFAULT_RETENTION_DAYS if retention_days is None else max(1, retention_days)


def _base_tags(job: str, platform: str, channel: str | None) -> dict[str, str]:
    return {
        "job": job,
        "platform": platform,
        "channel": channel or "-",
    }


def _merge_tags(
    base_tags: Mapping[str, str], permit_tags: Mapping[str, str] | None
) -> dict[str, str]:
    tags = dict(base_tags)
    if permit_tags:
        tags.update(dict(permit_tags))
    return tags


def _retain_recent(
    records: Iterable[_RecordT], *, cutoff: datetime, until: datetime
) -> list[_RecordT]:
    return [
        record
        for record in records
        if cutoff <= record.recorded_at <= until
    ]


def _summarize_send_events(
    records: Iterable[_SendEventRecord],
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    success: dict[str, int] = {}
    failure: dict[str, int] = {}
    histogram: dict[str, dict[str, int]] = {}
    for record in records:
        buckets = histogram.setdefault(record.job, {})
        bucket = _select_bucket(record.duration)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        if record.outcome == "success":
            success[record.job] = success.get(record.job, 0) + 1
        else:
            failure[record.job] = failure.get(record.job, 0) + 1
    return success, failure, histogram


def _calculate_success_rate(
    success: Mapping[str, int], failure: Mapping[str, int]
) -> dict[str, dict[str, float | int]]:
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
    return success_rate


def _build_snapshot(
    *,
    generated_at: datetime,
    success_rate: dict[str, dict[str, float | int]],
    histogram: dict[str, dict[str, int]],
    permit_denials: Iterable[_PermitDenialRecord],
) -> dict[str, object]:
    return {
        "generated_at": generated_at.isoformat(),
        "success_rate": success_rate,
        "latency_histogram_seconds": histogram,
        "permit_denials": _format_permit_denials(permit_denials),
    }


def _format_permit_denials(
    permit_denials: Iterable[_PermitDenialRecord],
) -> list[dict[str, str]]:
    return [dict(record.payload) for record in permit_denials]


def _select_bucket(value: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if value <= threshold:
            return label
    return _LATENCY_BUCKETS[-1][1]


def _trim_and_build_snapshot(
    *,
    send_events: Iterable[_SendEventRecord],
    permit_denials: Iterable[_PermitDenialRecord],
    generated_at: datetime,
    retention_days: int,
) -> tuple[
    dict[str, object],
    list[_SendEventRecord],
    list[_PermitDenialRecord],
]:
    cutoff = generated_at - timedelta(days=retention_days)
    trimmed_send_events = _retain_recent(
        send_events, cutoff=cutoff, until=generated_at
    )
    trimmed_permit_denials = _retain_recent(
        permit_denials, cutoff=cutoff, until=generated_at
    )
    success_counts, failure_counts, histogram = _summarize_send_events(
        trimmed_send_events
    )
    success_rate = _calculate_success_rate(success_counts, failure_counts)
    snapshot = _build_snapshot(
        generated_at=generated_at,
        success_rate=success_rate,
        histogram=histogram,
        permit_denials=trimmed_permit_denials,
    )
    return snapshot, trimmed_send_events, trimmed_permit_denials


def _prepare_send_success(
    *,
    recorded_at: datetime,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    permit_tags: Mapping[str, str] | None,
) -> tuple[_SendEventRecord, _MetricIncrementCall, _MetricObservationCall]:
    base_tags = _base_tags(job, platform, channel)
    increment_tags = _merge_tags(base_tags, permit_tags)
    observation_tags = {**base_tags, "unit": "seconds"}
    record = _SendEventRecord(
        recorded_at=recorded_at,
        job=job,
        outcome="success",
        duration=float(duration_seconds),
    )
    return (
        record,
        _MetricIncrementCall(name="send.success", tags=increment_tags),
        _MetricObservationCall(
            name="send.duration",
            value=float(duration_seconds),
            tags=observation_tags,
        ),
    )


def _prepare_send_failure(
    *,
    recorded_at: datetime,
    job: str,
    platform: str,
    channel: str | None,
    duration_seconds: float,
    error_type: str,
) -> tuple[_SendEventRecord, _MetricIncrementCall, _MetricObservationCall]:
    base_tags = _base_tags(job, platform, channel)
    increment_tags = dict(base_tags)
    increment_tags["error"] = error_type
    observation_tags = {**base_tags, "unit": "seconds"}
    record = _SendEventRecord(
        recorded_at=recorded_at,
        job=job,
        outcome="failure",
        duration=float(duration_seconds),
    )
    return (
        record,
        _MetricIncrementCall(name="send.failure", tags=increment_tags),
        _MetricObservationCall(
            name="send.duration",
            value=float(duration_seconds),
            tags=observation_tags,
        ),
    )


def _prepare_permit_denial(
    *,
    recorded_at: datetime,
    job: str,
    platform: str,
    channel: str | None,
    reason: str,
    permit_tags: Mapping[str, str] | None,
) -> tuple[_PermitDenialRecord, _MetricIncrementCall]:
    base_tags = _base_tags(job, platform, channel)
    tags = _merge_tags(base_tags, permit_tags)
    tags["reason"] = reason
    record = _PermitDenialRecord(recorded_at=recorded_at, payload=dict(tags))
    return record, _MetricIncrementCall(name="send.denied", tags=tags)


def _prepare_send_delay(
    *,
    job: str,
    platform: str,
    channel: str | None,
    delay_seconds: float,
) -> _MetricObservationCall:
    base_tags = _base_tags(job, platform, channel)
    observation_tags = {**base_tags, "unit": "seconds"}
    return _MetricObservationCall(
        name="send.delay_seconds",
        value=float(delay_seconds),
        tags=observation_tags,
    )


__all__ = [
    "_SendEventRecord",
    "_PermitDenialRecord",
    "_MetricIncrementCall",
    "_MetricObservationCall",
    "_MetricsHistory",
    "_LATENCY_BUCKETS",
    "_normalize_retention_days",
    "_base_tags",
    "_merge_tags",
    "_retain_recent",
    "_summarize_send_events",
    "_calculate_success_rate",
    "_build_snapshot",
    "_format_permit_denials",
    "_select_bucket",
    "_trim_and_build_snapshot",
    "_prepare_send_success",
    "_prepare_send_failure",
    "_prepare_permit_denial",
    "_prepare_send_delay",
]
