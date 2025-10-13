from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict


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
                self._data = new_data
                self._mtime = st.st_mtime
        except FileNotFoundError:
            # use empty defaults
            self._data = {}
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Failed to reload settings from %s: %s", self.path, exc)
