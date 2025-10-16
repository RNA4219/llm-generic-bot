from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import ContextManager, Mapping

import pytest

from llm_generic_bot.core.orchestrator import MetricsRecorder
from llm_generic_bot.infra.metrics import reporting

try:  # pragma: no cover
    from freezegun import freeze_time as _freezegun_freeze_time
except ModuleNotFoundError:  # pragma: no cover
    from datetime import datetime as _datetime
    from unittest.mock import patch

    @contextmanager
    def _freeze_time_impl(iso_timestamp: str) -> Generator[None, None, None]:
        frozen = _datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))

        class _Frozen(_datetime):
            @classmethod
            def now(cls, tz: timezone | None = None) -> _datetime:  # type: ignore[override]
                if tz is None:
                    return frozen
                return frozen.astimezone(tz)

            @classmethod
            def utcnow(cls) -> _datetime:  # type: ignore[override]
                return frozen.astimezone(timezone.utc).replace(tzinfo=None)

        with patch("datetime.datetime", _Frozen), patch("time.time", lambda: frozen.timestamp()):
            yield
else:  # pragma: no cover
    def _freeze_time_impl(iso_timestamp: str) -> ContextManager[None]:
        return _freezegun_freeze_time(iso_timestamp)


class RecordingMetrics(MetricsRecorder):
    def __init__(self) -> None:
        self.increment_calls: list[tuple[str, dict[str, str]]] = []
        self.observe_calls: list[tuple[str, float, dict[str, str]]] = []

    def increment(self, name: str, tags: Mapping[str, str] | None = None) -> None:
        self.increment_calls.append((name, dict(tags or {})))

    def observe(self, name: str, value: float, tags: Mapping[str, str] | None = None) -> None:
        self.observe_calls.append((name, value, dict(tags or {})))


@pytest.fixture(autouse=True)
def reset_metrics_module() -> Generator[None, None, None]:
    reporting.reset_for_test()
    try:
        yield
    finally:
        reporting.reset_for_test()


@pytest.fixture
def freeze_time_ctx() -> Callable[[str], ContextManager[None]]:
    return _freeze_time_impl


@pytest.fixture
def make_recording_metrics() -> Callable[[], RecordingMetrics]:
    return RecordingMetrics


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
