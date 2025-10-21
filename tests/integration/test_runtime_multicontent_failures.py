from __future__ import annotations

import asyncio
import json
import time
import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable

import pytest

from llm_generic_bot import main as main_module
from llm_generic_bot.config.quotas import PerChannelQuotaConfig
from llm_generic_bot.core.arbiter.gate import PermitGate
from llm_generic_bot.core.arbiter.models import (
    PermitGateConfig,
    PermitGateHooks,
    PermitQuotaLevel,
    PermitReevaluationOutcome,
    PermitRejectionContext,
)
from llm_generic_bot.core.orchestrator import PermitDecision
from llm_generic_bot.core.queue import CoalesceQueue
from llm_generic_bot.core.scheduler import Scheduler
from llm_generic_bot.features.dm_digest import DigestLogEntry
from llm_generic_bot.features.news import NewsFeedItem, SummaryError
from llm_generic_bot.infra import metrics as metrics_module
from llm_generic_bot.infra.metrics import aggregator_state

# LEGACY_MULTICONTENT_FAILURES_CHECKLIST:
# - tests.integration.runtime_multicontent.failures.test_permit
from tests.integration.runtime_multicontent.failures.test_permit import *  # noqa: F401,F403


async def _dispatch_twice_with_jitter(
    scheduler: Any,
    orchestrator: Any,
    *,
    base_ts: float,
    monkeypatch: pytest.MonkeyPatch,
) -> list[float]:
    delays: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        delays.append(duration)

    def _fake_next_slot(
        ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)
    ) -> float:
        return ts if not clash else ts + 5.0

    monkeypatch.setattr(scheduler, "_sleep", _fake_sleep)
    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", _fake_next_slot)

    _run_dispatch(scheduler, "first message", created_at=base_ts)
    await scheduler.dispatch_ready_batches(base_ts)

    _run_dispatch(scheduler, "second message", created_at=base_ts)
    await scheduler.dispatch_ready_batches(base_ts)

    await orchestrator.flush()
    return delays

pytestmark = pytest.mark.anyio("asyncio")


def _settings() -> Dict[str, Any]:
    settings: Dict[str, Any] = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    for key in ("weather", "omikuji", "dm_digest", "report"):
        cfg = settings.get(key)
        if isinstance(cfg, dict):
            cfg["enabled"] = False
    news = settings["news"]
    news["schedule"] = "00:00"
    news["priority"] = 5
    settings["cooldown"]["window_sec"] = 60
    settings["profiles"]["discord"]["channel"] = "discord-news"
    return settings


def _run_dispatch(
    scheduler: Any,
    text: str,
    *,
    created_at: float,
    batch_id: str | None = None,
) -> None:
    job = scheduler._jobs[0]
    scheduler.queue.push(
        text,
        priority=job.priority,
        job=job.name,
        created_at=created_at,
        channel=job.channel,
        batch_id=batch_id,
    )


def _providers(items: Iterable[NewsFeedItem], summarize: Any) -> tuple[Any, Any]:
    async def _fetch(_url: str, *, limit: int | None = None) -> Iterable[NewsFeedItem]:
        del _url, limit
        return list(items)

    return SimpleNamespace(fetch=_fetch), SimpleNamespace(summarize=summarize)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_permit_reevaluation_allows_after_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    settings["dedupe"]["enabled"] = False

    current_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: current_time)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("reeval", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    quota = PerChannelQuotaConfig(day=2, window_minutes=1, burst_limit=1)
    reevaluation_state: dict[str, float | None] = {"after": None}

    def time_fn() -> float:
        return current_time

    def _on_rejection(ctx: PermitRejectionContext) -> PermitReevaluationOutcome:
        del ctx
        reevaluation_state["after"] = current_time + 61.0
        return PermitReevaluationOutcome(
            level="per_channel",
            reason="retry after cooldown",
            retry_after=61.0,
            allowed=None,
        )

    gate = PermitGate(
        per_channel=quota,
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(PermitQuotaLevel(name="per_channel", quota=quota),),
            hooks=PermitGateHooks(on_rejection=_on_rejection),
        ),
    )

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        queue=queue,
        permit_gate=gate,
    )
    scheduler.jitter_enabled = False

    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=current_time)
    await scheduler.dispatch_ready_batches(current_time)
    await orchestrator.flush()

    scheduler._reevaluation_waits.clear()
    _run_dispatch(scheduler, text, created_at=current_time)
    await scheduler.dispatch_ready_batches(current_time)
    await orchestrator.flush()

    after = reevaluation_state["after"]
    assert after is not None
    current_time = after + 1.0

    _run_dispatch(scheduler, text, created_at=current_time)
    await scheduler.dispatch_ready_batches(current_time)
    await orchestrator.flush()

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {"success": 2, "failure": 0, "ratio": 1.0}


async def test_permit_reevaluation_schedules_retry_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    settings["dedupe"]["enabled"] = False

    current_time = {"value": 2_000_000.0}
    monkeypatch.setattr(time, "time", lambda: current_time["value"])

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("reeval", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    retry_after = 61.0

    def time_fn() -> float:
        return current_time["value"]

    hook_calls: list[str] = []

    def _on_rejection(ctx: PermitRejectionContext) -> PermitReevaluationOutcome:
        hook_calls.append(ctx.level)
        return PermitReevaluationOutcome(
            level=ctx.level,
            reason="retry after cooldown",
            retry_after=retry_after,
            allowed=True,
        )

    quota = PerChannelQuotaConfig(day=2, window_minutes=1, burst_limit=1)
    gate = PermitGate(
        per_channel=quota,
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(PermitQuotaLevel(name="per_channel", quota=quota),),
            hooks=PermitGateHooks(on_rejection=_on_rejection),
        ),
    )

    assert gate.permit("discord", "discord-news", "news").allowed is True

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        queue=queue,
        permit_gate=gate,
    )
    scheduler.jitter_enabled = False

    send_calls: list[tuple[str, str | None, str | None]] = []

    async def _fake_send(text: str, channel: str | None, *, job: str | None = None) -> None:
        send_calls.append((text, channel, job))

    monkeypatch.setattr(orchestrator._sender, "send", _fake_send)

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float, result: object = None) -> object:
        sleep_calls.append(delay)
        current_time["value"] += delay
        return result

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    caplog.set_level("INFO", logger="llm_generic_bot.core.orchestrator.runtime")

    text = await jobs["news"]()
    assert text

    batch_id = "permit-reeval-retry"
    _run_dispatch(scheduler, text, created_at=current_time["value"], batch_id=batch_id)
    await scheduler.dispatch_ready_batches(current_time["value"])
    await orchestrator.flush()
    await orchestrator.flush()

    assert send_calls == [(text, "discord-news", "news")]
    assert hook_calls == ["per_channel"]
    assert sleep_calls and sleep_calls[0] == pytest.approx(retry_after)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "send_permit_retry_scheduled"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "retry_after", None) == pytest.approx(retry_after)
    assert getattr(record, "reason", None) == "retry after cooldown"

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {"success": 1, "failure": 0, "ratio": 1.0}
    permit_denials = snapshot["permit_denials"]
    assert len(permit_denials) == 1
    denial_entry = permit_denials[0]
    assert denial_entry["reason"] == "burst limit reached"
    assert denial_entry["reevaluation_reason"] == "retry after cooldown"

    await orchestrator.close()


async def test_permit_reevaluation_retry_succeeds_with_audit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    settings["dedupe"]["enabled"] = False

    current_time = {"value": 3_000_000.0}
    monkeypatch.setattr(time, "time", lambda: current_time["value"])

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("reeval", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    retry_after = 61.0

    def time_fn() -> float:
        return current_time["value"]

    hook_calls: list[str] = []

    def _on_rejection(ctx: PermitRejectionContext) -> PermitReevaluationOutcome:
        hook_calls.append(ctx.level)
        return PermitReevaluationOutcome(
            level=ctx.level,
            reason="manual reevaluation",
            retry_after=retry_after,
            allowed=None,
        )

    quota = PerChannelQuotaConfig(day=2, window_minutes=1, burst_limit=1)
    gate = PermitGate(
        per_channel=quota,
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(PermitQuotaLevel(name="per_channel", quota=quota),),
            hooks=PermitGateHooks(on_rejection=_on_rejection),
        ),
    )

    assert gate.permit("discord", "discord-news", "news").allowed is True

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        queue=queue,
        permit_gate=gate,
    )
    scheduler.jitter_enabled = False

    send_calls: list[tuple[str, str | None, str | None]] = []

    async def _fake_send(text: str, channel: str | None, *, job: str | None = None) -> None:
        send_calls.append((text, channel, job))

    monkeypatch.setattr(orchestrator._sender, "send", _fake_send)

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float, result: object = None) -> object:
        sleep_calls.append(delay)
        current_time["value"] += delay
        return result

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    caplog.set_level("INFO", logger="llm_generic_bot.core.orchestrator.runtime")

    text = await jobs["news"]()
    assert text

    batch_id = "permit-reeval-success"
    _run_dispatch(scheduler, text, created_at=current_time["value"], batch_id=batch_id)
    await scheduler.dispatch_ready_batches(current_time["value"])
    await orchestrator.flush()

    assert hook_calls == ["per_channel"]
    assert sleep_calls and sleep_calls[0] == pytest.approx(retry_after)

    await asyncio.sleep(0)
    await orchestrator.flush()

    assert len(send_calls) == 1
    assert send_calls[0] == (text, "discord-news", "news")

    retry_logs = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "send_permit_retry_scheduled"
    ]
    assert retry_logs
    success_logs = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "send_success"
    ]
    assert success_logs

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {"success": 1, "failure": 0, "ratio": 1.0}
    permit_denials = snapshot["permit_denials"]
    assert permit_denials
    denial_entry = permit_denials[0]
    assert denial_entry["reason"] == "burst limit reached"
    assert denial_entry["reevaluation_reason"] == "manual reevaluation"
    assert denial_entry["reevaluation_reason_color"] == "red"

    await orchestrator.close()


async def test_quota_multilayer_quota_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)
    settings["dedupe"]["enabled"] = False

    current_time = 1_000_000.0

    monkeypatch.setattr(time, "time", lambda: current_time)

    per_channel_quota = PerChannelQuotaConfig(day=5, window_minutes=1, burst_limit=1)
    per_platform_quota = PerChannelQuotaConfig(day=2, window_minutes=5, burst_limit=1)

    def time_fn() -> float:
        return current_time

    gate = PermitGate(
        per_channel=per_channel_quota,
        time_fn=time_fn,
        config=PermitGateConfig(
            levels=(
                PermitQuotaLevel(name="per_channel", quota=per_channel_quota),
                PermitQuotaLevel(name="per_platform", quota=per_platform_quota),
            )
        ),
    )

    assert gate.permit("discord", "discord-news", "news").allowed is True

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        queue=queue,
        permit_gate=gate,
    )
    scheduler.jitter_enabled = False

    send_calls: list[tuple[str, str | None, str | None]] = []

    async def _fake_send(text: str, channel: str | None, *, job: str | None = None) -> None:
        send_calls.append((text, channel, job))

    monkeypatch.setattr(orchestrator._sender, "send", _fake_send)

    text = await jobs["news"]()
    batch_id = "quota-multilayer"
    _run_dispatch(scheduler, text, created_at=current_time, batch_id=batch_id)
    await scheduler.dispatch_ready_batches(current_time)
    await orchestrator.flush()

    assert send_calls == []

    denial_snapshot = aggregator_state.weekly_snapshot()
    assert denial_snapshot["permit_denials"]
    denial_entry = denial_snapshot["permit_denials"][0]
    assert denial_entry["reason"] == "burst limit reached"
    assert denial_entry["retryable"] == "true"
    assert denial_entry["retry_after_sec"] == "60"
    assert denial_entry["level"] == "per_channel"

    current_time += 61.0

    _run_dispatch(scheduler, text, created_at=current_time, batch_id=batch_id)
    await scheduler.dispatch_ready_batches(current_time)
    await orchestrator.flush()

    assert send_calls == []

    second_snapshot = aggregator_state.weekly_snapshot()
    assert len(second_snapshot["permit_denials"]) == 2
    second_entry = second_snapshot["permit_denials"][1]
    assert second_entry["job"] == "news"
    assert second_entry["platform"] == "discord"
    assert second_entry["channel"] == "discord-news"
    assert second_entry["level"] == "per_platform"
    assert second_entry["retry_after_sec"] == "239"
    assert second_entry["retryable"] == "true"

    current_time += 300.0

    _run_dispatch(scheduler, text, created_at=current_time, batch_id=batch_id)
    await scheduler.dispatch_ready_batches(current_time)
    await orchestrator.flush()

    assert len(send_calls) == 1

    snapshot = aggregator_state.weekly_snapshot()
    assert len(snapshot["permit_denials"]) == 2
    assert snapshot["success_rate"]["news"] == {"success": 1, "failure": 0, "ratio": 1.0}


async def test_quota_multilayer_retry_blocks_duplicate_dispatch() -> None:
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    send_calls: list[tuple[str, str | None, str | None]] = []

    class _Sender:
        platform = "discord"

        async def send(self, text: str, channel: str | None, *, job: str | None = None) -> None:
            send_calls.append((text, channel, job))

    scheduler = Scheduler(sender=_Sender(), queue=queue, jitter_enabled=False)
    scheduler.jitter_enabled = False

    batch_id = "quota-multilayer-hold"
    job = "news"
    channel = "discord-news"

    queue.mark_reevaluation_pending(
        batch_id,
        job=job,
        channel=channel,
        level="per_channel",
        until=60.0,
    )

    queue.push(
        "first",
        priority=5,
        job=job,
        created_at=10.0,
        channel=channel,
        batch_id=batch_id,
    )
    await scheduler.dispatch_ready_batches(10.0)
    assert send_calls == []

    queue.push(
        "second",
        priority=5,
        job=job,
        created_at=61.0,
        channel=channel,
        batch_id=batch_id,
    )
    await scheduler.dispatch_ready_batches(61.0)
    assert send_calls == [("second", channel, job)]

    queue.mark_reevaluation_pending(
        batch_id,
        job=job,
        channel=channel,
        level="per_platform",
        until=360.0,
    )

    queue.push(
        "third",
        priority=5,
        job=job,
        created_at=120.0,
        channel=channel,
        batch_id=batch_id,
    )
    await scheduler.dispatch_ready_batches(120.0)
    assert send_calls == [("second", channel, job)]

    queue.push(
        "final",
        priority=5,
        job=job,
        created_at=361.0,
        channel=channel,
        batch_id=batch_id,
    )
    await scheduler.dispatch_ready_batches(361.0)
    assert send_calls == [
        ("second", channel, job),
        ("final", channel, job),
    ]


async def test_scheduler_jitter_thresholds_override_preserves_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    scheduler_cfg = settings.setdefault("scheduler", {})
    scheduler_cfg["jitter_range_seconds"] = [7, 7]
    scheduler_cfg["queue"] = {"threshold": 1}

    calls: list[tuple[str, str | None, str]] = []

    class _PermitRecorder:
        def permit(self, platform: str, channel: str | None, job: str) -> PermitDecision:
            calls.append((platform, channel, job))
            return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("custom", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        permit_gate=_PermitRecorder(),
    )

    assert scheduler.jitter_range == (7, 7)
    assert getattr(scheduler.queue, "_threshold") == 1

    recorded_delay: list[float] = []
    jitter_calls: list[tuple[float, bool, tuple[int, int]]] = []

    async def _fake_sleep(duration: float) -> None:
        recorded_delay.append(duration)

    async def _fake_report_send_delay(
        *,
        job: str,
        platform: str,
        channel: str | None,
        delay_seconds: float,
    ) -> None:
        recorded_delay.append(delay_seconds)
        assert job == "news"
        assert platform == "discord"
        assert channel == "discord-news"

    def _fake_next_slot(
        ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)
    ) -> float:
        jitter_calls.append((ts, clash, jitter_range))
        if not clash:
            return ts
        return ts + float(jitter_range[0])

    base_ts = 1_000_000.0
    monkeypatch.setattr(scheduler, "_sleep", _fake_sleep)
    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", _fake_next_slot)
    monkeypatch.setattr(metrics_module, "report_send_delay", _fake_report_send_delay)

    text = await jobs["news"]()
    assert text

    _run_dispatch(scheduler, text, created_at=base_ts)
    await scheduler.dispatch_ready_batches(base_ts)

    scheduler._reevaluation_waits.clear()
    _run_dispatch(scheduler, text, created_at=base_ts)
    await scheduler.dispatch_ready_batches(base_ts)

    await orchestrator.flush()
    await orchestrator.close()

    assert recorded_delay == [0.0, pytest.approx(7.0), pytest.approx(7.0)]
    assert jitter_calls == [(base_ts, False, (7, 7)), (base_ts, True, (7, 7))]
    assert calls == [("discord", "discord-news", "news"), ("discord", "discord-news", "news")]


@pytest.mark.parametrize(
    "jitter_override,threshold_override",
    [((3, 15), 3), ((5, 9), 1)],
)
async def test_scheduler_config_toggles_maintain_delay_and_permit_metrics(
    monkeypatch: pytest.MonkeyPatch,
    jitter_override: tuple[int, int],
    threshold_override: int,
) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    scheduler_cfg = settings.setdefault("scheduler", {})
    scheduler_cfg["jitter_range_seconds"] = list(jitter_override)
    scheduler_cfg["queue"] = {"threshold": threshold_override, "window_sec": 0}
    settings["dedupe"]["enabled"] = False
    settings["cooldown"]["window_sec"] = 0
    settings["cooldown"]["jobs"]["news"]["base_gap_sec"] = 0

    recorded_delays: list[float] = []
    delay_metrics: list[float] = []
    jitter_calls: list[tuple[float, bool, tuple[int, int]]] = []

    async def _fake_sleep(duration: float) -> None:
        recorded_delays.append(duration)

    async def _fake_report_send_delay(
        *,
        job: str,
        platform: str,
        channel: str | None,
        delay_seconds: float,
    ) -> None:
        delay_metrics.append(delay_seconds)
        assert job == "news"
        assert platform == "discord"
        assert channel == "discord-news"

    def _fake_next_slot(
        ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)
    ) -> float:
        jitter_calls.append((ts, clash, jitter_range))
        if not clash:
            return ts
        return ts + float(jitter_range[0])

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("custom", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings)

    metrics_service = getattr(orchestrator._metrics_boundary, "service")  # type: ignore[attr-defined]
    assert metrics_service is not None

    base_ts = 1_000_000.0
    monkeypatch.setattr(scheduler, "_sleep", _fake_sleep)
    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", _fake_next_slot)
    monkeypatch.setattr(metrics_module, "report_send_delay", _fake_report_send_delay)

    text = await jobs["news"]()
    assert text

    _run_dispatch(scheduler, text, created_at=base_ts)
    await scheduler.dispatch_ready_batches(base_ts)

    scheduler._reevaluation_waits.clear()
    _run_dispatch(scheduler, text, created_at=base_ts)
    await scheduler.dispatch_ready_batches(base_ts)

    await orchestrator.flush()
    await orchestrator.close()

    assert jitter_calls
    effective_range = jitter_calls[0][2]
    expected_delay = float(effective_range[0])
    assert recorded_delays == [0.0, pytest.approx(expected_delay)]
    assert delay_metrics == [pytest.approx(expected_delay)]
    assert jitter_calls == [
        (base_ts, False, effective_range),
        (base_ts, True, effective_range),
    ]

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {"success": 2, "failure": 0, "ratio": 1.0}

    snapshot_result = metrics_service.collect_weekly_snapshot()
    metrics_snapshot = (
        await snapshot_result if inspect.isawaitable(snapshot_result) else snapshot_result
    )
    observations = metrics_snapshot.observations
    delay_thresholds = observations.get("send.delay_threshold_seconds")
    assert delay_thresholds is not None
    min_tags = tuple(
        sorted({"job": "news", "channel": "discord-news", "platform": "discord", "bound": "min"}.items())
    )
    max_tags = tuple(
        sorted({"job": "news", "channel": "discord-news", "platform": "discord", "bound": "max"}.items())
    )
    threshold_tags = tuple(
        sorted({"job": "news", "channel": "discord-news", "platform": "discord"}.items())
    )
    assert min_tags in delay_thresholds
    assert max_tags in delay_thresholds
    min_snapshot = delay_thresholds[min_tags]
    max_snapshot = delay_thresholds[max_tags]
    assert min_snapshot.minimum == pytest.approx(float(effective_range[0]))
    assert max_snapshot.maximum == pytest.approx(float(effective_range[1]))
    batch_thresholds = observations.get("send.batch_threshold_count")
    assert batch_thresholds is not None
    assert threshold_tags in batch_thresholds
    threshold_snapshot = batch_thresholds[threshold_tags]
    assert threshold_snapshot.minimum == pytest.approx(float(threshold_override))


@pytest.mark.parametrize(
    "variations",
    [
        (
            ((5, 11), 2, (2, 4)),
            ((9, 12), 4, (4, 8)),
        ),
        (
            ((6, 6), 3, (3, 6)),
            ((4, 8), 5, (4, 8)),
        ),
    ],
)
async def test_scheduler_jitter_threshold_variations_preserve_delay_and_permit_success(
    monkeypatch: pytest.MonkeyPatch,
    variations: tuple[tuple[tuple[int, int], int, tuple[int, int]], ...],
) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    scheduler_cfg = settings.setdefault("scheduler", {})
    first_range, first_threshold, _ = variations[0]
    scheduler_cfg["jitter_range_seconds"] = list(first_range)
    scheduler_cfg["queue"] = {"threshold": first_threshold, "window_sec": 0}
    settings["dedupe"]["enabled"] = False

    permit_calls: list[tuple[str, str | None, str]] = []

    class _PermitRecorder:
        def permit(self, platform: str, channel: str | None, job: str) -> PermitDecision:
            permit_calls.append((platform, channel, job))
            return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

    recorded_delays: list[float] = []
    delay_metrics: list[float] = []
    jitter_calls: list[tuple[float, bool, tuple[int, int]]] = []

    async def _fake_sleep(duration: float) -> None:
        recorded_delays.append(duration)

    async def _fake_report_send_delay(
        *,
        job: str,
        platform: str,
        channel: str | None,
        delay_seconds: float,
    ) -> None:
        delay_metrics.append(delay_seconds)
        assert job == "news"
        assert platform == "discord"
        assert channel == "discord-news"

    def _fake_next_slot(
        ts: float, clash: bool, jitter_range: tuple[int, int] = (60, 180)
    ) -> float:
        jitter_calls.append((ts, clash, jitter_range))
        if not clash:
            return ts
        return ts + float(jitter_range[0])

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("variation", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    scheduler, orchestrator, jobs = main_module.setup_runtime(
        settings,
        permit_gate=_PermitRecorder(),
    )

    base_ts = 2_000_000.0
    monkeypatch.setattr(scheduler, "_sleep", _fake_sleep)
    monkeypatch.setattr("llm_generic_bot.core.scheduler.next_slot", _fake_next_slot)
    monkeypatch.setattr(metrics_module, "report_send_delay", _fake_report_send_delay)

    await orchestrator.flush()

    news_text = await jobs["news"]()
    assert news_text

    for index, (jitter_override, threshold_override, expected_range) in enumerate(variations):
        scheduler.jitter_range = jitter_override
        scheduler.queue._threshold = threshold_override  # type: ignore[attr-defined]
        scheduler.queue._window = 0.0  # type: ignore[attr-defined]

        current_ts = base_ts + index * 100.0
        _run_dispatch(scheduler, news_text, created_at=current_ts)
        await scheduler.dispatch_ready_batches(current_ts)

        _run_dispatch(scheduler, news_text, created_at=current_ts)
        await scheduler.dispatch_ready_batches(current_ts)

        # Each variation should result in two jitter checks: a clash-free and a clashing dispatch.
        variation_calls = jitter_calls[index * 2 : index * 2 + 2]
        assert variation_calls == [
            (current_ts, False, expected_range),
            (current_ts, True, expected_range),
        ]

        expected_delay = float(expected_range[0])
        assert delay_metrics[index] == pytest.approx(expected_delay)
        assert recorded_delays[index * 2 : index * 2 + 2] == [
            pytest.approx(0.0),
            pytest.approx(expected_delay),
        ]

        await orchestrator.flush()

    await orchestrator.flush()
    await orchestrator.close()

    expected_total = len(variations) * 2
    assert len(permit_calls) == expected_total
    assert all(call == ("discord", "discord-news", "news") for call in permit_calls)

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {
        "success": expected_total,
        "failure": 0,
        "ratio": 1.0,
    }

async def test_cooldown_resume_allows_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    current = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: current)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        return f"summary-{language}"

    fetcher, summarizer = _providers([NewsFeedItem("title", "https://example.com", None)], _summarize)
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False
    orchestrator._cooldown.note_post("discord", "discord-news", "news")

    assert await jobs["news"]() is None
    current += settings["cooldown"]["window_sec"] + 1
    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=current)
    await scheduler.dispatch_ready_batches(current)
    await orchestrator.flush()

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {"success": 1, "failure": 0, "ratio": 1.0}
    await orchestrator.close()


async def test_summary_provider_retry_and_fallback(caplog: pytest.LogCaptureFixture) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    attempts = {"value": 0}

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del language
        attempts["value"] += 1
        if attempts["value"] == 1:
            raise SummaryError("temporary", retryable=True)
        raise SummaryError("fatal", retryable=False)

    fetcher, summarizer = _providers([NewsFeedItem("fallback", "https://example.com", None)], _summarize)
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer
    caplog.set_level("WARNING", logger="llm_generic_bot.features.news")

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = False

    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=0.0)
    await scheduler.dispatch_ready_batches()
    await orchestrator.flush()

    retry = [r for r in caplog.records if r.message == "news_summary_retry"]
    fallback = [r for r in caplog.records if r.message == "news_summary_fallback"]
    assert len(retry) == 1 and retry[0].attempt == 1
    assert len(fallback) == 1 and fallback[0].reason == "fatal"
    assert aggregator_state.weekly_snapshot()["success_rate"]["news"] == {"success": 1, "failure": 0, "ratio": 1.0}
    await orchestrator.close()


async def test_dm_digest_permit_denied_records_metrics() -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    dm_cfg = settings["dm_digest"]
    dm_cfg["enabled"] = True
    dm_cfg["source_channel"] = "dm-source"
    dm_cfg["recipient_id"] = "recipient-1"

    entry = DigestLogEntry(
        timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc),
        level="INFO",
        message="event happened",
    )

    async def _collect(channel: str, *, limit: int) -> Iterable[DigestLogEntry]:
        assert channel == "dm-source"
        assert limit == dm_cfg.get("max_events", 20)
        return [entry]

    async def _summarize(text: str, *, max_events: int | None = None) -> str:
        assert "event happened" in text
        assert max_events == dm_cfg.get("max_events", 20)
        return "summary"

    async def _send(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - should not be called
        raise AssertionError("sender should not be invoked when permit denies")

    dm_cfg["log_provider"] = SimpleNamespace(collect=_collect)
    dm_cfg["summary_provider"] = SimpleNamespace(summarize=_summarize)
    dm_cfg["sender"] = SimpleNamespace(send=_send)

    queue = CoalesceQueue(window_seconds=0.0, threshold=1)

    def _deny(_platform: str, _channel: str | None, job: str) -> PermitDecision:
        return PermitDecision(allowed=False, reason="quota", retryable=False, job=f"{job}-denied")

    permit_gate = SimpleNamespace(permit=_deny)

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue, permit_gate=permit_gate)
    scheduler.jitter_enabled = False

    result = await jobs["dm_digest"]()
    assert result is None

    snapshot = aggregator_state.weekly_snapshot()["permit_denials"]
    assert snapshot == [
        {
            "job": "dm_digest-denied",
            "platform": "discord_dm",
            "channel": "recipient-1",
            "reason": "quota",
            "retryable": "false",
        }
    ]

    await orchestrator.close()


async def test_jitter_delay_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    aggregator_state.reset_for_test()
    settings = _settings()
    queue = CoalesceQueue(window_seconds=1.0, threshold=1)

    async def _summarize(_item: NewsFeedItem, *, language: str = "ja") -> str:
        del _item, language
        return "summary"

    fetcher, summarizer = _providers(
        [NewsFeedItem("title", "https://example.com", None)],
        _summarize,
    )
    settings["news"]["feed_provider"] = fetcher
    settings["news"]["summary_provider"] = summarizer

    scheduler, orchestrator, jobs = main_module.setup_runtime(settings, queue=queue)
    scheduler.jitter_enabled = True
    scheduler.jitter_range = (3, 3)

    delays: list[float] = []

    async def _capture_sleep(duration: float) -> None:
        delays.append(duration)

    monkeypatch.setattr(scheduler, "_sleep", _capture_sleep, raising=False)
    scheduler._last_dispatch_ts = 1.0

    text = await jobs["news"]()
    assert text
    _run_dispatch(scheduler, text, created_at=0.0)

    await scheduler.dispatch_ready_batches(1.0)
    await orchestrator.flush()

    assert delays == [pytest.approx(3.0)]

    snapshot = aggregator_state.weekly_snapshot()
    assert snapshot["success_rate"]["news"] == {"success": 1, "failure": 0, "ratio": 1.0}

    metrics_snapshot = await orchestrator.weekly_snapshot()
    tags_key = (
        ("channel", "discord-news"),
        ("job", "news"),
        ("platform", "discord"),
        ("unit", "seconds"),
    )
    assert "send.delay_seconds" in metrics_snapshot.observations
    delay_stats = metrics_snapshot.observations["send.delay_seconds"][tags_key]
    assert delay_stats.count == 1
    assert delay_stats.minimum == pytest.approx(3.0)
    assert delay_stats.maximum == pytest.approx(3.0)
    assert delay_stats.average == pytest.approx(3.0)

    await orchestrator.close()
