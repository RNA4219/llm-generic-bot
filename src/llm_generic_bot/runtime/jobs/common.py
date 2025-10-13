from __future__ import annotations

from importlib import import_module
from typing import Any, Mapping, Optional


def as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def get_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_enabled(config: Mapping[str, Any], *, default: bool = True) -> bool:
    flag = config.get("enabled")
    if flag is None:
        return default
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, (int, float)):
        return bool(flag)
    if isinstance(flag, str):
        lowered = flag.strip().lower()
        if lowered in {"", "0", "false", "off"}:
            return False
        if lowered in {"1", "true", "on"}:
            return True
    return default


def optional_str(value: object) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _schedule_values(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple, set)):
        return [str(value) for value in raw if isinstance(value, str) and value]
    return []


def collect_schedules(config: Mapping[str, Any], *, default: str) -> tuple[str, ...]:
    schedules = _schedule_values(config.get("schedule"))
    schedules.extend(_schedule_values(config.get("schedules")))
    return tuple(schedules or [default])


def resolve_object(value: str) -> object:
    module_path, sep, attr_path = value.partition(":")
    if not sep:
        module_path, _, attr_path = value.rpartition(".")
    if not module_path or not attr_path:
        raise ValueError(f"invalid reference: {value}")
    module = import_module(module_path)
    obj: object = module
    for attr in attr_path.split("."):
        obj = getattr(obj, attr)
    return obj


def resolve_configured_object(value: object, *, context: str) -> object | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return resolve_object(value)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"{context}: failed to resolve '{value}'") from exc
    return value


__all__ = [
    "as_mapping",
    "collect_schedules",
    "get_float",
    "is_enabled",
    "optional_str",
    "resolve_configured_object",
    "resolve_object",
]
