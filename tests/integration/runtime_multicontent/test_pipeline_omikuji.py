from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any, Dict, List

import pytest

from llm_generic_bot import main as main_module

from ._helpers import (
    create_queue,
    freeze_scheduler,
    record_orchestrator_enqueue,
    record_queue_push,
)


pytestmark = pytest.mark.anyio("asyncio")


async def test_omikuji_job_registers_and_enqueues_when_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()

    omikuji_calls: List[Dict[str, Any]] = []

    async def fake_omikuji(
        cfg: Dict[str, Any],
        *,
        user_id: str,
        today: Any | None = None,
    ) -> str:
        omikuji_calls.append({"cfg": cfg, "user_id": user_id, "today": today})
        return "omikuji-post"

    monkeypatch.setattr(main_module, "build_omikuji_post", fake_omikuji)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "omikuji": {
            "schedule": "07:00",
            "user_id": "fortune-user",
            "templates": [{"id": "t1", "text": "template"}],
            "fortunes": ["lucky"],
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    freeze_scheduler(monkeypatch, scheduler)

    enqueue_calls = record_orchestrator_enqueue(monkeypatch, orchestrator)
    pushed_jobs = record_queue_push(monkeypatch, scheduler)

    tz = zoneinfo.ZoneInfo("UTC")
    now = dt.datetime(2024, 1, 1, 7, 0, tzinfo=tz)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now.timestamp())

    try:
        assert "omikuji" in jobs
        assert omikuji_calls and omikuji_calls[-1]["user_id"] == "fortune-user"
        assert [call.job for call in pushed_jobs] == ["omikuji"]
        assert enqueue_calls and enqueue_calls[-1].job == "omikuji"
        assert enqueue_calls[-1].channel == "general"
    finally:
        await orchestrator.close()
