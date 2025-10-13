"""Sprint 3: 週次サマリ機能のテストスケルトン."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Mapping

import pytest

from llm_generic_bot.core import orchestrator as orchestrator_module

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture(name="anyio_backend")
def _anyio_backend() -> str:
    return "asyncio"


@dataclass
class ReportMock:
    expected_snapshot: Mapping[str, Any] | None = None
    expected_fallback: str | None = None
    return_value: Mapping[str, Any] = field(default_factory=lambda: {"body": "", "attachments": {"tags": {}}})
    calls: list[dict[str, Any]] = field(default_factory=list, init=False)

    async def build_weekly_report(self, snapshot: Mapping[str, Any], *, fallback_body: str) -> Mapping[str, Any]:
        self.calls.append({"snapshot": snapshot, "fallback_body": fallback_body})
        if self.expected_snapshot is not None:
            assert snapshot == self.expected_snapshot
        if self.expected_fallback is not None:
            assert fallback_body == self.expected_fallback
        return self.return_value


@dataclass
class MetricsMock:
    snapshot: Mapping[str, Any] | None = None
    calls: list[dict[str, Any]] = field(default_factory=list, init=False)

    def weekly_snapshot(self, *args: Any, **kwargs: Any) -> Mapping[str, Any] | None:
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.snapshot


@pytest.fixture
def mock_report_module(monkeypatch: pytest.MonkeyPatch) -> ReportMock:
    mock = ReportMock()
    module = ModuleType("llm_generic_bot.features.report")
    module.build_weekly_report = mock.build_weekly_report
    monkeypatch.setitem(sys.modules, "llm_generic_bot.features.report", module)
    return mock


@pytest.fixture
def mock_metrics_facade(monkeypatch: pytest.MonkeyPatch) -> MetricsMock:
    mock = MetricsMock()
    module = ModuleType("llm_generic_bot.infra.metrics")
    module.weekly_snapshot = mock.weekly_snapshot
    monkeypatch.setitem(sys.modules, "llm_generic_bot.infra.metrics", module)
    return mock


@dataclass(frozen=True)
class Scenario:
    name: str
    metrics_snapshot: Mapping[str, Any] | None
    expected_snapshot: Mapping[str, Any]
    fallback_body: str
    report_return: Mapping[str, Any]
    expected_result: Mapping[str, Any]


HAPPY_SNAPSHOT: Mapping[str, Any] = {"range": {"start": "2025-01-06", "end": "2025-01-12"}, "totals": {"delivered": 128, "failed": 4}, "top_channels": [{"channel": "discord-news", "count": 48}, {"channel": "discord-weather", "count": 32}]}
HAPPY_TAGS = {"range": "2025-W02", "has_incidents": "false"}
FALLBACK_SNAPSHOT: Mapping[str, Any] = {"range": None, "totals": {"delivered": 0, "failed": 0}, "incidents": []}
FALLBACK_TAGS = {"range": "unknown", "has_incidents": "unknown"}

SCENARIOS = (
    Scenario(
        "happy_path",
        HAPPY_SNAPSHOT,
        HAPPY_SNAPSHOT,
        "📊 週次レポート: 今週もお疲れさまでした。",
        {"body": "📊 OPS ウィークリーレポート\n- 成功: 128\n- 失敗: 4", "attachments": {"tags": HAPPY_TAGS}},
        {"body": "📊 OPS ウィークリーレポート\n- 成功: 128\n- 失敗: 4", "channel": "ops-weekly", "attachments": {"tags": {"job": "weekly_report", **HAPPY_TAGS}}},
    ),
    Scenario(
        "missing_metrics",
        None,
        FALLBACK_SNAPSHOT,
        "📊 今週のメトリクスは未取得です。",
        {"body": "📊 今週のメトリクスは未取得です。", "attachments": {"tags": FALLBACK_TAGS}},
        {"body": "📊 今週のメトリクスは未取得です。", "channel": "ops-weekly", "attachments": {"tags": {"job": "weekly_report", **FALLBACK_TAGS}}},
    ),
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_weekly_report_flow(
    scenario: Scenario,
    mock_report_module: ReportMock,
    mock_metrics_facade: MetricsMock,
) -> None:
    mock_metrics_facade.snapshot = scenario.metrics_snapshot
    mock_report_module.expected_snapshot = scenario.expected_snapshot
    mock_report_module.expected_fallback = scenario.fallback_body
    mock_report_module.return_value = scenario.report_return

    result = await orchestrator_module.compose_weekly_report(
        channel="ops-weekly",
        job_tag="weekly_report",
        fallback_body=scenario.fallback_body,
    )

    assert result == scenario.expected_result
    assert len(mock_metrics_facade.calls) == 1
    assert mock_metrics_facade.calls[0]["args"] == ()
    assert mock_metrics_facade.calls[0]["kwargs"] == {}
    assert len(mock_report_module.calls) == 1
