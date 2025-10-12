from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue


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
