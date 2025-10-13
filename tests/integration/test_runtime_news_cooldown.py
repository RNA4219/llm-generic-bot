from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.core.queue import CoalesceQueue


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_news_job_skips_send_when_cooldown_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    permit_args: List[Dict[str, Any]] = []
    cooldown_results: List[bool] = []

    async def fake_build_news_post(
        cfg: Dict[str, Any],
        *,
        feed_provider: Any,
        summary_provider: Any,
        permit: Any,
        cooldown: Any,
    ) -> Optional[str]:
        assert callable(permit)
        assert callable(cooldown)
        job_name = str(cfg.get("job", "news"))
        cooldown_active = await cooldown(
            job=job_name,
            platform=str(cfg.get("platform")) if cfg.get("platform") else None,
            channel=str(cfg.get("channel")) if cfg.get("channel") else None,
        )
        cooldown_results.append(cooldown_active)
        if cooldown_active:
            return None
        permit(job=job_name, suppress_cooldown=False)
        permit_args.append({"job": job_name, "suppress_cooldown": False})
        return "ok"

    monkeypatch.setattr(main_module, "build_news_post", fake_build_news_post)

    async def dummy_fetch(_url: str, *, limit: int | None = None) -> list[str]:  # noqa: ARG001
        return []

    async def dummy_summarize(*_: Any, **__: Any) -> str:
        return "summary"

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "cooldown": {"window_sec": 3600},
        "news": {
            "schedule": "00:00",
            "channel": "news",
            "feed_provider": SimpleNamespace(fetch=dummy_fetch),
            "summary_provider": SimpleNamespace(summarize=dummy_summarize),
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)

    async def fake_enqueue(*_: Any, **__: Any) -> None:
        raise AssertionError("enqueue should not be called when cooldown is active")

    monkeypatch.setattr(orchestrator, "enqueue", fake_enqueue)

    orchestrator._cooldown.note_post("discord", "news", "news")

    result = await jobs["news"]()
    assert result is None

    await scheduler.dispatch_ready_batches()

    assert cooldown_results == [True]
    assert permit_args == []


async def test_news_job_resumes_after_cooldown_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    base_time = 1_700_000_000.0
    current_time = base_time

    def fake_time() -> float:
        return current_time

    monkeypatch.setattr(time, "time", fake_time)

    permit_args: List[Dict[str, Any]] = []
    cooldown_results: List[bool] = []
    enqueue_calls: List[Dict[str, Any]] = []

    async def fake_build_news_post(
        cfg: Dict[str, Any],
        *,
        feed_provider: Any,
        summary_provider: Any,
        permit: Any,
        cooldown: Any,
    ) -> Optional[str]:
        job_name = str(cfg.get("job", "news"))
        cooldown_active = await cooldown(
            job=job_name,
            platform=str(cfg.get("platform")) if cfg.get("platform") else None,
            channel=str(cfg.get("channel")) if cfg.get("channel") else None,
        )
        cooldown_results.append(cooldown_active)
        if cooldown_active:
            return None
        permit(job=job_name, suppress_cooldown=False)
        permit_args.append({"job": job_name, "suppress_cooldown": False})
        return "ok"

    monkeypatch.setattr(main_module, "build_news_post", fake_build_news_post)

    async def dummy_fetch(_url: str, *, limit: int | None = None) -> list[str]:  # noqa: ARG001
        return []

    async def dummy_summarize(*_: Any, **__: Any) -> str:
        return "summary"

    settings: Dict[str, Any] = {
        "timezone": "UTC",
        "profiles": {"discord": {"enabled": True, "channel": "general"}},
        "cooldown": {"window_sec": 60},
        "news": {
            "schedule": "00:00",
            "priority": 5,
            "job": "news",
            "channel": "news",
            "feed_provider": SimpleNamespace(fetch=dummy_fetch),
            "summary_provider": SimpleNamespace(summarize=dummy_summarize),
        },
    }

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)

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

    scheduler.jitter_enabled = False

    async def immediate_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(scheduler, "_sleep", immediate_sleep)

    orchestrator._cooldown.note_post("discord", "news", "news")

    result_first = await jobs["news"]()
    assert result_first is None
    await scheduler.dispatch_ready_batches(current_time)

    assert cooldown_results == [True]
    assert permit_args == []
    assert enqueue_calls == []

    current_time = base_time + settings["cooldown"]["window_sec"] + 1

    result_second = await jobs["news"]()
    assert result_second == "ok"

    scheduler.queue.push(
        result_second,
        priority=settings["news"]["priority"],
        job=settings["news"].get("job", "news"),
        created_at=current_time,
        channel=settings["news"]["channel"],
    )

    await scheduler.dispatch_ready_batches(current_time)

    assert cooldown_results == [True, False]
    assert permit_args == [{"job": "news", "suppress_cooldown": False}]
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["job"] == "news"
