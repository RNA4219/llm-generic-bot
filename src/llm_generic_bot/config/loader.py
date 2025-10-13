from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Mapping


_LOGGER = logging.getLogger(__name__)


class Settings:
    def __init__(self, path: str):
        self.path = path
        self._data: Dict[str, Any] = {}
        self._mtime = 0.0
        self.reload(force=True)

    @property
    def data(self) -> Dict[str, Any]:
        self.reload()  # hot reload if changed
        return self._data

    def reload(self, force: bool = False) -> None:
        try:
            st = os.stat(self.path)
            if force or st.st_mtime > self._mtime:
                with open(self.path, "r", encoding="utf-8") as f:
                    new_data = json.load(f)
                diff = _diff_mapping(self._data, new_data)
                if diff:
                    _LOGGER.info(
                        "Settings reloaded from %s",
                        self.path,
                        extra={"event": "settings_reload", "diff": diff},
                    )
                self._data = new_data
                self._mtime = st.st_mtime
        except FileNotFoundError:
            # use empty defaults
            self._data = {}
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Failed to reload settings from %s: %s", self.path, exc)


_MISSING = object()


def _diff_mapping(old: Mapping[str, Any], new: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    diff: Dict[str, Dict[str, Any]] = {}

    def _walk(old_value: Any, new_value: Any, path: tuple[str, ...]) -> None:
        if isinstance(old_value, Mapping) and isinstance(new_value, Mapping):
            keys = set(old_value) | set(new_value)
            for key in sorted(keys):
                child_path = path + (str(key),)
                prev = old_value.get(key, _MISSING)
                curr = new_value.get(key, _MISSING)
                if isinstance(prev, Mapping) and isinstance(curr, Mapping):
                    _walk(prev, curr, child_path)
                else:
                    if prev is _MISSING and curr is _MISSING:
                        continue
                    if prev is _MISSING or curr is _MISSING or prev != curr:
                        diff[".".join(child_path)] = {
                            "old": None if prev is _MISSING else prev,
                            "new": None if curr is _MISSING else curr,
                        }
            return

        if old_value != new_value:
            key = ".".join(path) or "<root>"
            diff[key] = {"old": old_value, "new": new_value}

    _walk(old, new, ())
    return diff
