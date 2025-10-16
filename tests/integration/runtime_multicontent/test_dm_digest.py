from __future__ import annotations

import datetime as dt
import zoneinfo
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.dm_digest import DigestLogEntry


pytestmark = pytest.mark.anyio("asyncio")


async def test_dm_digest_job_sends_without_scheduler_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    async def collect_logs(_channel: str, *, limit: int) -> List[DigestLogEntry]:
        del limit
        return [
            DigestLogEntry(
                timestamp=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
                level="INFO",
                message="event",
            )
        ]

    async def summarize(_text: str, *, max_events: int | None = None) -> str:
        del max_events
        return "summary"

    dm_sender_calls: List[str] = []

    async def dm_send(
        text: str,
        *_: Any,
        job: Optional[str] = None,
        recipient_id: Optional[str] = None,
        **__: Any,
    ) -> None:
        dm_sender_calls.append(f"{job}:{recipient_id}:{text}")

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "dm_digest": {
            "schedule": "08:00",
            "source_channel": "logs",
            "recipient_id": "user-1",
            "log_provider": SimpleNamespace(collect=collect_logs),
            "summary_provider": SimpleNamespace(summarize=summarize),
            "sender": SimpleNamespace(send=dm_send),
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    pushed_jobs: List[str] = []

    def spy_push(
        _text: str,
        *,
        priority: int,
        job: str,
        created_at: Optional[float] = None,
        channel: Optional[str] = None,
    ) -> None:
        del priority, created_at, channel
        pushed_jobs.append(job)

    monkeypatch.setattr(scheduler.queue, "push", spy_push)
    tz = zoneinfo.ZoneInfo("UTC")
    await scheduler._run_due_jobs(dt.datetime(2024, 1, 1, 8, 0, tzinfo=tz))

    assert "dm_digest" in jobs
    assert pushed_jobs == []
    assert dm_sender_calls == ["dm_digest:user-1:Daily Digest\nsummary"]

    await orchestrator.close()
