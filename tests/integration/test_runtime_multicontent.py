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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_setup_runtime_registers_all_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    async def dummy_fetch(_url: str, *, limit: int | None = None) -> list[str]:  # noqa: ARG001
        return []

    async def dummy_summarize(*_: Any, **__: Any) -> str:
        return "summary"

    async def dummy_collect(_channel: str, *, limit: int) -> list[str]:  # noqa: ARG001
        return ["entry"] * limit

    async def dummy_send(
        _text: str,
        _channel: Optional[str] = None,
        *,
        correlation_id: Optional[str] = None,
        job: Optional[str] = None,
        recipient_id: Optional[str] = None,
    ) -> None:  # noqa: ARG001
        return None

    weather_calls: List[Dict[str, Any]] = []
    news_calls: List[Dict[str, Any]] = []
    omikuji_calls: List[Dict[str, Any]] = []
    dm_calls: List[Dict[str, Any]] = []

    async def fake_weather(cfg: Dict[str, Any]) -> str:
        weather_calls.append(cfg)
        return "weather-post"

    async def fake_news(cfg: Dict[str, Any], **kwargs: Any) -> str:
        news_calls.append({"cfg": cfg, **kwargs})
        return "news-post"

    async def fake_omikuji(cfg: Dict[str, Any], *, user_id: str, today: Any | None = None) -> str:
        omikuji_calls.append({"cfg": cfg, "user_id": user_id, "today": today})
        return "omikuji-post"

    async def fake_dm_digest(cfg: Dict[str, Any], **kwargs: Any) -> str:
        dm_calls.append({"cfg": cfg, **kwargs})
        return "dm-post"

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather)
    monkeypatch.setattr(main_module, "build_news_post", fake_news)
    monkeypatch.setattr(main_module, "build_omikuji_post", fake_omikuji)
    monkeypatch.setattr(main_module, "build_dm_digest", fake_dm_digest)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"schedule": "00:00"},
        "news": {
            "schedule": "06:00",
            "feed_provider": SimpleNamespace(fetch=dummy_fetch),
            "summary_provider": SimpleNamespace(summarize=dummy_summarize),
            "channel": "news-channel",
        },
        "omikuji": {
            "schedule": "07:00",
            "user_id": "fortune-user",
            "templates": [{"id": "t1", "text": "template"}],
            "fortunes": ["lucky"],
        },
        "dm_digest": {
            "schedule": "08:00",
            "source_channel": "dm-source",
            "recipient_id": "recipient-1",
            "log_provider": SimpleNamespace(collect=dummy_collect),
            "summary_provider": SimpleNamespace(summarize=dummy_summarize),
            "sender": SimpleNamespace(send=dummy_send),
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        queue=queue,
    )
    scheduler.jitter_enabled = False

    async def no_sleep(_delay: float) -> None:
        return None

    scheduler._sleep = no_sleep  # type: ignore[assignment]

    enqueue_calls: List[Dict[str, Any]] = []
    pushed_jobs: List[str] = []

    async def fake_enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        enqueue_calls.append(
            {
                "text": text,
                "job": job,
                "platform": platform,
                "channel": channel,
                "correlation_id": correlation_id,
            }
        )
        return "corr"

    monkeypatch.setattr(orchestrator, "enqueue", fake_enqueue)

    original_push = scheduler.queue.push

    def spy_push(
        text: str,
        *,
        priority: int,
        job: str,
        created_at: Optional[float] = None,
        channel: Optional[str] = None,
    ) -> None:
        pushed_jobs.append(job)
        original_push(
            text,
            priority=priority,
            job=job,
            created_at=created_at,
            channel=channel,
        )

    monkeypatch.setattr(scheduler.queue, "push", spy_push)

    assert set(jobs) == {"weather", "news", "omikuji", "dm_digest"}

    tz = zoneinfo.ZoneInfo("UTC")
    schedule_checks = [
        (dt.datetime(2024, 1, 1, 0, 0, tzinfo=tz), "weather"),
        (dt.datetime(2024, 1, 1, 6, 0, tzinfo=tz), "news"),
        (dt.datetime(2024, 1, 1, 7, 0, tzinfo=tz), "omikuji"),
        (dt.datetime(2024, 1, 1, 8, 0, tzinfo=tz), "dm_digest"),
    ]

    for now, expected_job in schedule_checks:
        previous_calls = len(enqueue_calls)
        await scheduler._run_due_jobs(now)
        await scheduler.dispatch_ready_batches(now.timestamp())
        if expected_job == "dm_digest":
            assert len(enqueue_calls) == previous_calls
        else:
            assert len(enqueue_calls) == previous_calls + 1
            assert enqueue_calls[-1]["job"] == expected_job

    assert [call["channel"] for call in enqueue_calls] == [
        "general",
        "news-channel",
        "general",
    ]

    assert pushed_jobs == ["weather", "news", "omikuji"]

    assert weather_calls and news_calls and omikuji_calls and dm_calls

    await orchestrator.close()


async def test_dm_digest_job_sends_without_scheduler_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    async def collect_logs(_channel: str, *, limit: int) -> List[DigestLogEntry]:
        del limit
        return [DigestLogEntry(timestamp=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc), level="INFO", message="event")]

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
