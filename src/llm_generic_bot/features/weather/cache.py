from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, cast

CacheSnapshot = dict[str, dict[str, Any]]
CachePayload = dict[str, CacheSnapshot]

DEFAULT_CACHE_PATH = Path("weather_cache.json")


def coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, value))


def read_cache(path: Path | None = None) -> CachePayload:
    actual_path = path or DEFAULT_CACHE_PATH
    if not actual_path.exists():
        return {}
    try:
        raw = json.loads(actual_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    payload: CachePayload = {}
    for key, value in raw.items():
        payload[str(key)] = coerce_snapshot(value)
    return payload


def write_cache(data: Mapping[str, Mapping[str, Any]], path: Path | None = None) -> None:
    actual_path = path or DEFAULT_CACHE_PATH
    serialisable: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        serialisable[str(key)] = {k: dict(v) for k, v in value.items()}
    actual_path.write_text(
        json.dumps(serialisable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def coerce_snapshot(value: object) -> CacheSnapshot:
    snapshot: CacheSnapshot = {}
    if not isinstance(value, Mapping):
        return snapshot
    for city, data in value.items():
        if isinstance(city, str) and isinstance(data, Mapping):
            snapshot[city] = dict(data)
    return snapshot


def filter_cache_entries(
    source: Mapping[str, Mapping[str, Any]],
    *,
    retention_seconds: float,
    now_ts: float | None = None,
) -> CacheSnapshot:
    timestamp = now_ts if now_ts is not None else time.time()
    kept: CacheSnapshot = {}
    for city, snapshot in source.items():
        ts_value = coerce_float(snapshot.get("ts")) if isinstance(snapshot, Mapping) else None
        if ts_value is None or timestamp - ts_value > retention_seconds:
            continue
        kept[city] = dict(snapshot)
    return kept


def resolve_snapshots(
    cache: Mapping[str, Mapping[str, Any]],
    *,
    retention_seconds: float,
    now_ts: float,
) -> tuple[CacheSnapshot, CacheSnapshot]:
    previous_today_source = coerce_snapshot(cache.get("today"))
    previous_today = filter_cache_entries(
        previous_today_source,
        retention_seconds=retention_seconds,
        now_ts=now_ts,
    )

    yesterday_source = coerce_snapshot(cache.get("yesterday"))
    if previous_today:
        yesterday = previous_today
    else:
        yesterday = filter_cache_entries(
            yesterday_source,
            retention_seconds=retention_seconds,
            now_ts=now_ts,
        )
    return previous_today, yesterday


def rotate_cache(
    *,
    today: Mapping[str, Mapping[str, Any]],
    previous_today: Mapping[str, Mapping[str, Any]],
    retention_seconds: float,
    now_ts: float,
) -> CachePayload:
    yesterday = filter_cache_entries(
        previous_today,
        retention_seconds=retention_seconds,
        now_ts=now_ts,
    )
    today_snapshot: CacheSnapshot = {city: dict(snapshot) for city, snapshot in today.items()}
    return {"today": today_snapshot, "yesterday": yesterday}


__all__ = [
    "CachePayload",
    "CacheSnapshot",
    "DEFAULT_CACHE_PATH",
    "clamp_unit_interval",
    "coerce_float",
    "coerce_snapshot",
    "filter_cache_entries",
    "read_cache",
    "resolve_snapshots",
    "rotate_cache",
    "write_cache",
]
