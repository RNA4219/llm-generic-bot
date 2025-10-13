from __future__ import annotations

import datetime as dt
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

    base_ts = 1_000_000.0
    clock = {"now": base_ts}

    def fake_time() -> float:
        return clock["now"]

    monkeypatch.setattr(main_module.time, "time", fake_time)
    monkeypatch.setattr("llm_generic_bot.core.cooldown.time.time", fake_time)

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

    scheduler, orchestrator, _ = main_module.setup_runtime(settings, queue=queue)

    async def fake_enqueue(*args: Any, **kwargs: Any) -> str:
        enqueue_calls.append({"args": args, "kwargs": kwargs})
        return "cid"

    monkeypatch.setattr(orchestrator, "enqueue", fake_enqueue)

    clock["now"] = base_ts
    orchestrator._cooldown.note_post("discord", "news", "news")

    clock["now"] = base_ts + 10.0
    now_dt = dt.datetime(2020, 1, 1, 0, 0, tzinfo=scheduler.tz)
    await scheduler._run_due_jobs(now_dt)
    await scheduler.dispatch_ready_batches(clock["now"])

    assert enqueue_calls == []

    clock["now"] = base_ts + orchestrator._cooldown.window + 10.0
    await scheduler._run_due_jobs(now_dt)
    await scheduler.dispatch_ready_batches(clock["now"])

    assert cooldown_results == [True, False]
    assert permit_args == [{"job": "news", "suppress_cooldown": False}]
    assert len(enqueue_calls) == 1
