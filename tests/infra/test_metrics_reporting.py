from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.anyio
@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
 
def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class _FrozenTime:
    def __init__(self, value: str) -> None:
        self._current = _parse_iso(value)
    def __enter__(self) -> "_FrozenTime":
        return self
    def __exit__(self, exc_type, exc, tb) -> None:
        return None
    def now(self) -> datetime:
        return self._current
    def move_to(self, value: str) -> datetime:
        self._current = _parse_iso(value)
        return self._current


sys.modules.setdefault("freezegun", SimpleNamespace(freeze_time=lambda value: _FrozenTime(value)))
from freezegun import freeze_time

from llm_generic_bot.infra.metrics import MetricsService


async def test_metrics_reporting_weekly_snapshot() -> None:
    tags = {"job": "weather", "platform": "slack", "channel": "alerts"}
    with freeze_time("2024-01-08T09:00:00Z") as frozen:
        service = MetricsService.create(backend="inmemory", clock=frozen.now)
        frozen.move_to("2024-01-01T09:00:00Z")
        service.record_event("send.success", tags=tags, measurements={"duration_sec": 5.0})
        frozen.move_to("2024-01-10T09:00:00Z")

        async def _call(
            name: str,
            *,
            measurements: dict[str, float] | None = None,
            extra: dict[str, str] | None = None,
        ) -> None:
            service.record_event(name, tags={**tags, **(extra or {})}, measurements=measurements)

        await asyncio.gather(
            _call("send.success", measurements={"duration_sec": 0.25}),
            _call("send.success", measurements={"duration_sec": 0.75}),
            _call("send.failure"),
            _call("send.denied", extra={"retryable": "false"}),
            _call("send.denied", extra={"retryable": "true"}),
        )

        frozen.move_to("2024-01-15T09:00:00Z")
        snapshot: dict[str, Any] = await service.collect_weekly_snapshot()

    assert snapshot == {
        "window": {"start": "2024-01-08T09:00:00+00:00", "end": "2024-01-15T09:00:00+00:00"},
        "metrics": {
            "send.denied": [
                {"count": 1, "tags": {**tags, "retryable": "false"}},
                {"count": 1, "tags": {**tags, "retryable": "true"}},
            ],
            "send.duration.histogram": [
                {
                    "tags": tags,
                    "sum": "1.000",
                    "count": 2,
                    "buckets": [
                        {"le": "0.500", "count": 1},
                        {"le": "1.000", "count": 2},
                        {"le": "+Inf", "count": 2},
                    ],
                }
            ],
            "send.success_rate": [
                {"tags": tags, "success": 2, "failure": 1, "rate": "0.667"}
            ],
        },
    }


async def test_metrics_reporting_uses_null_backend_when_uninitialized() -> None:
    with freeze_time("2024-01-08T09:00:00Z") as frozen:
        service = MetricsService.create(backend=None, clock=frozen.now)
        service.record_event("send.success", tags={"job": "weather", "platform": "slack", "channel": "alerts"}, measurements={"duration_sec": 0.5})
        frozen.move_to("2024-01-15T09:00:00Z")
        snapshot = await service.collect_weekly_snapshot()
    assert snapshot == {}
