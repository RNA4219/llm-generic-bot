from __future__ import annotations

import datetime as dt
import zoneinfo
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from llm_generic_bot import main as main_module

from ._helpers import (
    create_queue,
    freeze_scheduler,
    record_orchestrator_enqueue,
    record_queue_push,
)


pytestmark = pytest.mark.anyio("asyncio")


async def test_dm_digest_job_registers_without_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = create_queue()

    async def dummy_collect(_channel: str, *, limit: int) -> list[str]:  # noqa: ARG001
        return ["entry"] * limit

    async def dummy_summarize(*_: Any, **__: Any) -> str:
        return "summary"

    dm_calls: List[Dict[str, Any]] = []
    sender_spy: AsyncMock = AsyncMock()

    async def fake_dm_digest(cfg: Dict[str, Any], **kwargs: Any) -> str:
        dm_calls.append({"cfg": cfg, **kwargs})
        sender = kwargs["sender"]
        job_name = str(cfg.get("job", "dm_digest"))
        recipient_id = str(cfg["recipient_id"])
        await sender.send("dm-post", None, job=job_name, recipient_id=recipient_id)
        return "dm-post"

    monkeypatch.setattr(main_module, "build_dm_digest", fake_dm_digest)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "dm_digest": {
            "schedule": "08:00",
            "source_channel": "dm-source",
            "recipient_id": "recipient-1",
            "log_provider": SimpleNamespace(collect=dummy_collect),
            "summary_provider": SimpleNamespace(summarize=dummy_summarize),
            "sender": SimpleNamespace(send=sender_spy),
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    freeze_scheduler(monkeypatch, scheduler)

    enqueue_calls = record_orchestrator_enqueue(monkeypatch, orchestrator)
    pushed_jobs = record_queue_push(monkeypatch, scheduler)

    tz = zoneinfo.ZoneInfo("UTC")
    now = dt.datetime(2024, 1, 1, 8, 0, tzinfo=tz)
    await scheduler._run_due_jobs(now)
    await scheduler.dispatch_ready_batches(now.timestamp())

    try:
        assert "dm_digest" in jobs
        assert dm_calls
        assert [call.job for call in pushed_jobs] == []
        assert enqueue_calls == []
        sender_spy.assert_awaited()
    finally:
        await orchestrator.close()
