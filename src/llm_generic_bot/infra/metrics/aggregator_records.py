from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
class _PermitReevaluationRecord:
    recorded_at: datetime
    payload: dict[str, str]


_LATENCY_BUCKETS: tuple[tuple[float, str], ...] = (
    (1.0, "1s"),
    (3.0, "3s"),
    (float("inf"), ">3s"),
)


_RecordT = TypeVar("_RecordT", _SendEventRecord, _PermitDenialRecord, _PermitReevaluationRecord)


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


def _retain_recent(records: Iterable[_RecordT], cutoff: datetime) -> list[_RecordT]:
    return [record for record in records if record.recorded_at >= cutoff]


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
    permit_reevaluations: Iterable[_PermitReevaluationRecord],
) -> dict[str, object]:
    return {
        "generated_at": generated_at.isoformat(),
        "success_rate": success_rate,
        "latency_histogram_seconds": histogram,
        "permit_denials": _format_permit_denials(permit_denials),
        "permit_reevaluations": _format_permit_reevaluations(permit_reevaluations),
    }


def _format_permit_denials(
    permit_denials: Iterable[_PermitDenialRecord],
) -> list[dict[str, str]]:
    return [dict(record.payload) for record in permit_denials]


def _format_permit_reevaluations(
    reevaluations: Iterable[_PermitReevaluationRecord],
) -> list[dict[str, str]]:
    return [dict(record.payload) for record in reevaluations]


def _select_bucket(value: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if value <= threshold:
            return label
    return _LATENCY_BUCKETS[-1][1]


__all__ = [
    "_SendEventRecord",
    "_PermitDenialRecord",
    "_PermitReevaluationRecord",
    "_LATENCY_BUCKETS",
    "_normalize_retention_days",
    "_base_tags",
    "_merge_tags",
    "_retain_recent",
    "_summarize_send_events",
    "_calculate_success_rate",
    "_build_snapshot",
    "_format_permit_denials",
    "_format_permit_reevaluations",
    "_select_bucket",
]
