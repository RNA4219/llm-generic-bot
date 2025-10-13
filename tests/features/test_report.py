"""Sprint 3: 週次サマリ機能の TDD 仕様テスト."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, Tuple

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision


class _DummySender:
    async def send(self, text: str, channel: str | None = None, *, job: str | None = None) -> None:
        return None


NOW = datetime(2024, 3, 4, tzinfo=timezone.utc)


def _snapshot(count: int | None) -> SimpleNamespace:
    counters = {"bot.messages": {(): SimpleNamespace(count=count)}} if count is not None else {}
    return SimpleNamespace(
        start=NOW - timedelta(days=7),
        end=NOW,
        counters=counters,
        observations={},
    )


CASES: Tuple[Dict[str, Any], ...] = (
    {"id": "happy_path", "snapshot": _snapshot(42), "expected": {
        "body": "📊 運用サマリ (02/26-03/03)\n・総投稿: 42 件",
        "channel": "ops-weekly",
        "tags": ("weekly_report", "ops"),
    }},
    {"id": "missing_metrics", "snapshot": _snapshot(None), "expected": {
        "body": "📊 運用サマリ: 今週のメトリクスは未取得です",
        "channel": "ops-weekly",
        "tags": ("weekly_report", "fallback"),
    }},
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_weekly_report_generation_spec(
    case: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("llm_generic_bot.features.report")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    collected: list[Any] = []
    summaries: list[SimpleNamespace] = []

    async def fake_collect(metrics: Any) -> SimpleNamespace:
        collected.append(metrics)
        return case["snapshot"]

    async def fake_summary(snapshot: SimpleNamespace) -> Dict[str, Any]:
        summaries.append(snapshot)
        return case["expected"]

    monkeypatch.setattr(module, "generate_weekly_summary", fake_summary, raising=False)
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.collect_weekly_snapshot",
        fake_collect,
    )

    orchestrator = Orchestrator(
        sender=_DummySender(),
        cooldown=CooldownGate(60, 1.0, 2.0, 0.1, 0.1, 0.1),
        dedupe=NearDuplicateFilter(),
        permit=lambda platform, channel, job: PermitDecision.allowed(job),
        metrics=None,
        platform="discord",
    )

    try:
        result = await orchestrator.weekly_snapshot()
    finally:
        await orchestrator.close()

    assert collected == [None], "メトリクススナップショット取得が呼ばれていない"
    assert summaries == [case["snapshot"]], "週次サマリ生成が未呼び出し"
    assert isinstance(result, dict), "Orchestrator.weekly_snapshot は dict を返すべき"
    assert result == case["expected"]
    assert "weekly_report" in result["tags"], "タグに週次識別子が含まれる必要がある"
    if case["id"] == "missing_metrics":
        assert "未取得" in result["body"]
