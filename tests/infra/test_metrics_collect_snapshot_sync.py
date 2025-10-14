from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping

from llm_generic_bot.infra import collect_weekly_snapshot
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot


class _SyncMetricsBackend:
    def __init__(self, snapshot: WeeklyMetricsSnapshot) -> None:
        self._snapshot = snapshot

    def record_event(
        self,
        name: str,
        *,
        tags: Mapping[str, str] | None = None,
        measurements: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        return None

    def collect_weekly_snapshot(self) -> WeeklyMetricsSnapshot:
        return self._snapshot


async def _collect_with_sync_backend(
    backend: _SyncMetricsBackend,
) -> WeeklyMetricsSnapshot:
    return await collect_weekly_snapshot(backend)


def test_collect_weekly_snapshot_allows_sync_backends() -> None:
    snapshot = WeeklyMetricsSnapshot(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 8, tzinfo=timezone.utc),
        counters={"send.success": {(): CounterSnapshot(count=1)}},
        observations={},
    )
    backend = _SyncMetricsBackend(snapshot)

    result = asyncio.run(_collect_with_sync_backend(backend))

    assert result is snapshot
