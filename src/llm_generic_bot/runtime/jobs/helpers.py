from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Any, Optional, cast

from ...features.weather import ReactionHistoryProvider


def as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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


def schedule_values(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [str(value) for value in raw if isinstance(value, str) and value]
    return []


def collect_schedules(config: Mapping[str, Any], *, default: str) -> list[str]:
    schedules = schedule_values(config.get("schedule"))
    schedules.extend(schedule_values(config.get("schedules")))
    return schedules or [default]


def optional_str(value: object) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


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
        except Exception as exc:  # pragma: no cover - validation path
            raise ValueError(f"{context}: failed to resolve '{value}'") from exc
    return value


def resolve_history_provider(value: object) -> Optional[ReactionHistoryProvider]:
    if value is None:
        return None
    if isinstance(value, str):
        resolved = resolve_object(value)
        return cast(Optional[ReactionHistoryProvider], resolved)
    return cast(Optional[ReactionHistoryProvider], value)
