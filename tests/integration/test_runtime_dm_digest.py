from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.core.orchestrator import PermitDecision
from llm_generic_bot.features.dm_digest import DigestLogEntry


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_dm_digest_job_returns_none_and_skips_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    build_calls: List[Dict[str, Any]] = []

    async def fake_build_dm_digest(cfg: Dict[str, Any], **kwargs: Any) -> str:
        build_calls.append({"cfg": cfg, **kwargs})
        return "digest-body"

    monkeypatch.setattr(main_module, "build_dm_digest", fake_build_dm_digest)

    log_provider = object()
    summary_provider = object()
    dm_sender = object()

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "dm_digest": {
            "schedule": "00:00",
            "source_channel": "dm-source",
            "recipient_id": "recipient-1",
            "log_provider": log_provider,
            "summary_provider": summary_provider,
            "sender": dm_sender,
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    enqueue_calls: List[Dict[str, Optional[str]]] = []

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
        return "corr-id"

    monkeypatch.setattr(orchestrator, "enqueue", fake_enqueue)

    job = jobs["dm_digest"]
    result = await job()

    assert len(build_calls) == 1
    assert build_calls[0]["cfg"] is settings["dm_digest"]
    assert build_calls[0]["log_provider"] is log_provider
    assert build_calls[0]["summarizer"] is summary_provider
    assert build_calls[0]["sender"] is dm_sender

    assert result is None

    await scheduler.dispatch_ready_batches()

    assert enqueue_calls == []

    await orchestrator.close()


async def test_dm_digest_job_denied_by_permit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    permit_gate = SimpleNamespace(permit=lambda _platform, _channel, job: PermitDecision.allowed(job))

    log_entries = [
        DigestLogEntry(
            timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            level="INFO",
            message="event happened",
        )
    ]

    async def fake_collect(channel: str, *, limit: int) -> List[DigestLogEntry]:
        assert channel == "dm-source"
        assert limit == 50
        return log_entries

    async def fake_summarize(text: str, *, max_events: int | None = None) -> str:
        assert "event happened" in text
        assert max_events == 50
        return "summary"

    sender_calls: List[Dict[str, Any]] = []

    async def fake_send(
        text: str,
        channel: Optional[str] = None,
        *,
        correlation_id: Optional[str] = None,
        job: Optional[str] = None,
        recipient_id: Optional[str] = None,
    ) -> None:
        sender_calls.append(
            {
                "text": text,
                "channel": channel,
                "correlation_id": correlation_id,
                "job": job,
                "recipient_id": recipient_id,
            }
        )

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "dm_digest": {
            "schedule": "00:00",
            "source_channel": "dm-source",
            "recipient_id": "recipient-1",
            "log_provider": SimpleNamespace(collect=fake_collect),
            "summary_provider": SimpleNamespace(summarize=fake_summarize),
            "sender": SimpleNamespace(send=fake_send),
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings, queue=queue, permit_gate=permit_gate
    )
    scheduler.jitter_enabled = False

    real_build = main_module.build_dm_digest
    build_results: List[Optional[str]] = []

    async def spy_build_dm_digest(*args: Any, **kwargs: Any) -> Optional[str]:
        result = await real_build(*args, **kwargs)
        build_results.append(result)
        return result

    monkeypatch.setattr(main_module, "build_dm_digest", spy_build_dm_digest)

    permit_calls: List[Dict[str, Optional[str]]] = []

    def denied_permit(platform: str, channel: Optional[str], job: str) -> PermitDecision:
        permit_calls.append({"platform": platform, "channel": channel, "job": job})
        return PermitDecision(allowed=False, reason="quota", retryable=False, job=f"{job}-denied")

    monkeypatch.setattr(permit_gate, "permit", denied_permit)

    caplog.set_level("INFO", logger="llm_generic_bot.features.dm_digest")

    job = jobs["dm_digest"]
    result = await job()

    assert result is None
    assert build_results == [None]
    assert permit_calls == [
        {"platform": "discord_dm", "channel": "recipient-1", "job": "dm_digest"}
    ]
    assert sender_calls == []

    denied_records = [
        record for record in caplog.records if record.message == "dm_digest_permit_denied"
    ]
    assert len(denied_records) == 1
    denied_record = denied_records[0]
    assert getattr(denied_record, "event") == "dm_digest_permit_denied"
    assert getattr(denied_record, "retryable") is False
    assert getattr(denied_record, "job") == "dm_digest-denied"

    await orchestrator.close()
