from __future__ import annotations

import datetime as dt
import sys
import zoneinfo
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.features.dm_digest import DigestLogEntry
from llm_generic_bot.features.news import NewsFeedItem
from llm_generic_bot.infra.metrics import CounterSnapshot, WeeklyMetricsSnapshot


_PROVIDERS_MODULE = "llm_generic_bot.runtime.providers"
if _PROVIDERS_MODULE not in sys.modules:
    providers_module = ModuleType(_PROVIDERS_MODULE)

    async def _sample_fetch(_url: str, *, limit: int | None = None) -> list[NewsFeedItem]:
        del limit
        return []

    async def _sample_summarize(item: NewsFeedItem, *, language: str = "ja") -> str:
        del language
        return item.summary or item.title

    async def _sample_collect(_channel: str, *, limit: int) -> list[DigestLogEntry]:
        del _channel, limit
        return []

    async def _sample_digest(text: str, *, max_events: int | None = None) -> str:
        del text, max_events
        return ""

    async def _sample_send(
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        del text, channel, correlation_id, job, recipient_id
        return None

    providers_module.SAMPLE_NEWS_FEED = SimpleNamespace(fetch=_sample_fetch)  # type: ignore[attr-defined]
    providers_module.SAMPLE_NEWS_SUMMARY = SimpleNamespace(summarize=_sample_summarize)  # type: ignore[attr-defined]
    providers_module.SAMPLE_DM_LOG = SimpleNamespace(collect=_sample_collect)  # type: ignore[attr-defined]
    providers_module.SAMPLE_DM_SUMMARY = SimpleNamespace(summarize=_sample_digest)  # type: ignore[attr-defined]
    providers_module.SAMPLE_DM_SENDER = SimpleNamespace(send=_sample_send)  # type: ignore[attr-defined]
    sys.modules[_PROVIDERS_MODULE] = providers_module


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_setup_runtime_uses_weather_channel_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    weather_calls: List[Dict[str, Any]] = []

    async def fake_weather(
        cfg: Dict[str, Any],
        *,
        channel: Optional[str] = None,
        job: str = "weather",
    ) -> str:
        weather_calls.append({"cfg": cfg, "channel": channel, "job": job})
        return "weather-post"

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"schedule": "00:00", "channel": "weather-alerts"},
    }

    scheduler, _orchestrator, _jobs = main_module.setup_runtime(
        settings,
        queue=queue,
    )

    pushed: List[Dict[str, Any]] = []

    def spy_push(
        text: str,
        *,
        priority: int,
        job: str,
        created_at: Optional[float] = None,
        channel: Optional[str] = None,
    ) -> None:
        pushed.append(
            {
                "text": text,
                "priority": priority,
                "job": job,
                "created_at": created_at,
                "channel": channel,
            }
        )

    monkeypatch.setattr(scheduler.queue, "push", spy_push)

    now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=scheduler.tz)
    await scheduler._run_due_jobs(now)

    assert weather_calls
    assert weather_calls[0]["channel"] == "weather-alerts"
    assert pushed
    assert pushed[0]["channel"] == "weather-alerts"


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


async def test_setup_runtime_skips_weather_job_when_disabled() -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"enabled": False, "schedule": "00:00"},
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)

    try:
        assert "weather" not in jobs
        assert all(job.name != "weather" for job in scheduler._jobs)
    finally:
        await orchestrator.close()


async def test_setup_runtime_uses_custom_weather_job_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    custom_job = "daily_weather"

    weather_calls: List[Dict[str, Any]] = []

    async def fake_weather_post(
        settings: Dict[str, Any],
        *,
        reaction_history_provider: Optional[object] = None,
        cooldown: object | None = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
        job: Optional[str] = None,
    ) -> str:
        del settings, reaction_history_provider, cooldown, platform, channel
        weather_calls.append({"job": job})
        return "weather-text"

    async def fake_history_provider(
        *,
        job: str,
        limit: int,
        platform: Optional[str],
        channel: Optional[str],
    ) -> list[int]:
        del job, limit, platform, channel
        return []

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather_post)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {
            "schedule": "00:00",
            "job": custom_job,
            "engagement": {"history_provider": fake_history_provider},
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    async def no_sleep(_delay: float) -> None:
        return None

    scheduler._sleep = no_sleep  # type: ignore[assignment]

    enqueue_calls: List[Dict[str, Any]] = []

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

    pushed_jobs: List[str] = []
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

    try:
        assert set(jobs) == {custom_job}
        assert [job.name for job in scheduler._jobs] == [custom_job]

        tz = zoneinfo.ZoneInfo("UTC")
        now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=tz)
        await scheduler._run_due_jobs(now)
        await scheduler.dispatch_ready_batches(now.timestamp())

        assert weather_calls == [{"job": custom_job}]
        assert pushed_jobs == [custom_job]
        assert enqueue_calls and enqueue_calls[-1]["job"] == custom_job
    finally:
        await orchestrator.close()


async def test_weather_job_uses_weather_channel_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    recorded_channels: List[Optional[str]] = []

    async def fake_weather_post(
        settings: Dict[str, Any],
        *,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> str:
        del settings, platform
        recorded_channels.append(channel)
        return "weather-text"

    monkeypatch.setattr(main_module, "build_weather_post", fake_weather_post)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"schedule": "00:00", "channel": "weather-override"},
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    async def no_sleep(_delay: float) -> None:
        return None

    scheduler._sleep = no_sleep  # type: ignore[assignment]

    enqueue_calls: List[Dict[str, Any]] = []

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

    try:
        assert set(jobs) == {"weather"}

        tz = zoneinfo.ZoneInfo("UTC")
        now = dt.datetime(2024, 1, 1, 0, 0, tzinfo=tz)
        await scheduler._run_due_jobs(now)
        await scheduler.dispatch_ready_batches(now.timestamp())

        assert recorded_channels == ["weather-override"]
        assert [call["channel"] for call in enqueue_calls] == ["weather-override"]
    finally:
        await orchestrator.close()


async def test_weekly_report_job_uses_metrics_and_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    snapshot = WeeklyMetricsSnapshot(
        start=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
        end=dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc),
        counters={"send.success": {(): CounterSnapshot(count=4)}},
        observations={},
    )

    class RecordingMetricsService:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.calls = 0

        def record_event(
            self,
            name: str,
            *,
            tags: Optional[Dict[str, str]] = None,
            measurements: Optional[Dict[str, float]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            del name, tags, measurements, metadata
            return None

        async def collect_weekly_snapshot(
            self, now: dt.datetime | None = None
        ) -> WeeklyMetricsSnapshot:
            del now
            self.calls += 1
            return snapshot

    from llm_generic_bot.runtime import setup as runtime_setup

    metrics_service = RecordingMetricsService()
    monkeypatch.setattr(runtime_setup, "MetricsService", lambda *_: metrics_service)

    weekly_snapshot_calls: List[Dict[str, Any]] = []

    def fake_weekly_snapshot() -> Dict[str, Any]:
        payload = {
            "generated_at": "2024-01-08T00:00:00+00:00",
            "success_rate": {"weather": {"ratio": 0.75}},
            "latency_histogram_seconds": {},
            "permit_denials": [],
        }
        weekly_snapshot_calls.append(payload)
        return payload

    monkeypatch.setattr(runtime_setup.metrics_module, "weekly_snapshot", fake_weekly_snapshot)

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "metrics": {"backend": "memory"},
        "report": {
            "enabled": True,
            "job": "weekly_report",
            "schedule": "09:00",
            "channel": "ops-weekly",
            "priority": 7,
            "permit": {
                "platform": "discord",
                "channel": "ops-weekly",
                "job": "weekly_report",
            },
            "template": {
                "title": "📊 運用サマリ ({week_range})",
                "line": "・{metric}: {value}",
                "footer": "詳細は運用ダッシュボードを参照",
            },
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)

    enqueue_calls: List[Dict[str, Any]] = []

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

    assert "weekly_report" in jobs

    job_func = jobs["weekly_report"]
    text = await job_func()

    assert metrics_service.calls == 1
    assert len(weekly_snapshot_calls) == 1
    assert isinstance(text, str)
    lines = text.splitlines()
    assert lines[0] == "📊 運用サマリ (2024-01-01〜2024-01-08)"
    assert "weather" in lines[1] and "75%" in lines[1]
    assert lines[-1] == "詳細は運用ダッシュボードを参照"

    await scheduler.sender.send(text, job="weekly_report")
    assert enqueue_calls and enqueue_calls[-1]["job"] == "weekly_report"
    assert enqueue_calls[-1]["platform"] == "discord"
    assert enqueue_calls[-1]["channel"] == "ops-weekly"

    await orchestrator.close()


async def test_setup_runtime_resolves_string_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    module_name = "tests.integration.fake_providers"
    provider_module = ModuleType(module_name)

    fetch_calls: list[dict[str, object]] = []

    async def fetch(url: str, *, limit: int | None = None) -> list[NewsFeedItem]:
        fetch_calls.append({"url": url, "limit": limit})
        return [NewsFeedItem(title="t", link="https://example.com", summary=None)]

    summary_calls: list[dict[str, object]] = []

    async def summarize(item: NewsFeedItem, *, language: str = "ja") -> str:
        summary_calls.append({"title": item.title, "language": language})
        return "summary"

    log_calls: list[dict[str, object]] = []

    async def collect(channel: str, *, limit: int) -> list[DigestLogEntry]:
        log_calls.append({"channel": channel, "limit": limit})
        return [
            DigestLogEntry(
                timestamp=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
                level="INFO",
                message="log",
            )
        ]

    digest_summary_calls: list[dict[str, object]] = []

    async def digest_summarize(
        text: str,
        *,
        max_events: int | None = None,
        **_: object,
    ) -> str:
        digest_summary_calls.append({"text": text, "max_events": max_events})
        return "digest"

    sender_calls: list[dict[str, object]] = []

    async def digest_send(
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        sender_calls.append(
            {
                "text": text,
                "channel": channel,
                "job": job,
                "recipient_id": recipient_id,
                "correlation_id": correlation_id,
            }
        )

    provider_module.news_feed = SimpleNamespace(fetch=fetch)  # type: ignore[attr-defined]
    provider_module.news_summary = SimpleNamespace(summarize=summarize)  # type: ignore[attr-defined]
    provider_module.dm_logs = SimpleNamespace(collect=collect)  # type: ignore[attr-defined]
    provider_module.dm_summary = SimpleNamespace(summarize=digest_summarize)  # type: ignore[attr-defined]
    provider_module.dm_sender = SimpleNamespace(send=digest_send)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, provider_module)

    settings: dict[str, object] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "weather": {"enabled": False},
        "omikuji": {"enabled": False},
        "news": {
            "schedule": "06:00",
            "feed_provider": f"{module_name}:news_feed",
            "summary_provider": f"{module_name}:news_summary",
            "feed_url": "https://example.com/rss",
        },
        "dm_digest": {
            "schedule": "08:00",
            "source_channel": "dm-source",
            "recipient_id": "recipient-1",
            "log_provider": f"{module_name}:dm_logs",
            "summary_provider": f"{module_name}:dm_summary",
            "sender": f"{module_name}:dm_sender",
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    async def no_sleep(_delay: float) -> None:
        return None

    scheduler._sleep = no_sleep  # type: ignore[assignment]

    enqueue_calls: list[dict[str, object]] = []

    async def fake_enqueue(
        text: str,
        *,
        job: str,
        platform: str,
        channel: str | None = None,
        correlation_id: str | None = None,
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

    tz = zoneinfo.ZoneInfo("UTC")

    await scheduler._run_due_jobs(dt.datetime(2024, 1, 1, 6, 0, tzinfo=tz))
    await scheduler.dispatch_ready_batches(dt.datetime(2024, 1, 1, 6, 0, tzinfo=tz).timestamp())

    await scheduler._run_due_jobs(dt.datetime(2024, 1, 1, 8, 0, tzinfo=tz))

    assert "news" in jobs and "dm_digest" in jobs
    assert fetch_calls and summary_calls
    assert log_calls and digest_summary_calls and sender_calls
    assert enqueue_calls and enqueue_calls[-1]["job"] == "news"
    assert sender_calls[-1]["recipient_id"] == "recipient-1"

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
