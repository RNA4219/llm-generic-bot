from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Iterable

__all__ = ["log_settings_diff"]


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _merge_keys(*mappings: Mapping[str, Any]) -> Iterable[str]:
    keys: set[str] = set()
    for mapping in mappings:
        keys.update(mapping.keys())
    return sorted(keys)


def _walk_diff(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    *,
    prefix: str = "",
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key in _merge_keys(old, new):
        path = f"{prefix}.{key}" if prefix else key
        in_old = key in old
        in_new = key in new
        if not in_old and in_new:
            changes.append({"path": path, "type": "added", "value": new[key]})
            continue
        if in_old and not in_new:
            changes.append({"path": path, "type": "removed", "value": old[key]})
            continue
        old_value = old[key]
        new_value = new[key]
        old_mapping = _as_mapping(old_value)
        new_mapping = _as_mapping(new_value)
        if old_mapping and new_mapping:
            nested = _walk_diff(old_mapping, new_mapping, prefix=path)
            changes.extend(nested)
            continue
        if old_value != new_value:
            changes.append(
                {
                    "path": path,
                    "type": "changed",
                    "old": old_value,
                    "new": new_value,
                }
            )
    return changes


async def log_settings_diff(
    logger: logging.Logger,
    *,
    old_settings: Mapping[str, Any],
    new_settings: Mapping[str, Any],
) -> None:
    changes = _walk_diff(old_settings, new_settings)
    if not changes:
        return
    payload = {"event": "settings_diff", "changes": changes}
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
