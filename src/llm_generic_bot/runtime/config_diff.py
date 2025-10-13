from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _normalize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): val for key, val in value.items()}


def _merge_diff(added: dict[str, Any], removed: dict[str, Any], changed: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    if added:
        diff["added"] = added
    if removed:
        diff["removed"] = removed
    if changed:
        diff["changed"] = changed
    return diff


def _compute_mapping_diff(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    prev_dict = _normalize_mapping(previous)
    curr_dict = _normalize_mapping(current)

    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, Any] = {}

    prev_keys = set(prev_dict)
    curr_keys = set(curr_dict)

    for key in curr_keys - prev_keys:
        added[key] = curr_dict[key]

    for key in prev_keys - curr_keys:
        removed[key] = prev_dict[key]

    for key in prev_keys & curr_keys:
        prev_value = prev_dict[key]
        curr_value = curr_dict[key]
        if isinstance(prev_value, Mapping) and isinstance(curr_value, Mapping):
            nested_diff = _compute_mapping_diff(prev_value, curr_value)
            if nested_diff:
                changed[key] = nested_diff
        elif prev_value != curr_value:
            changed[key] = {"old": prev_value, "new": curr_value}

    return _merge_diff(added, removed, changed)


def compute_diff(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Compute a nested dictionary diff similar to DeepDiff for mappings."""

    diff = _compute_mapping_diff(previous, current)
    return diff
