from __future__ import annotations

import asyncio

import pytest

from llm_generic_bot.infra import metrics as metrics_module

from llm_generic_bot.runtime.setup import setup_runtime


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_setup_runtime_raises_when_no_profiles_enabled() -> None:
    settings = {
        "profiles": {
            "discord": {"enabled": False},
            "misskey": {"enabled": False},
        }
    }

    with pytest.raises(ValueError):
        setup_runtime(settings)


def test_setup_runtime_disables_discord_via_string_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": "false"},
            "misskey": {"enabled": True, "channel": "general"},
        }
    }

    _, orchestrator, _ = setup_runtime(settings)

    assert getattr(orchestrator, "_default_platform") == "misskey"
    asyncio.run(orchestrator.close())


def test_setup_runtime_disables_misskey_via_string_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": "false"},
        }
    }

    _, orchestrator, _ = setup_runtime(settings)

    assert getattr(orchestrator, "_default_platform") == "discord"
    asyncio.run(orchestrator.close())


def test_setup_runtime_raises_when_profiles_disabled_via_string_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": "false"},
            "misskey": {"enabled": "false"},
        }
    }

    with pytest.raises(ValueError):
        setup_runtime(settings)


@pytest.mark.anyio("asyncio")
async def test_setup_runtime_disables_metrics_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics_module.reset_for_test()
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "metrics": {"enabled": False},
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
    }

    _, orchestrator, _ = setup_runtime(settings)

    snapshot = metrics_module.weekly_snapshot()
    assert metrics_module._AGGREGATOR.backend_configured is False
    assert snapshot["success_rate"] == {}
    assert snapshot["latency_histogram_seconds"] == {}
    assert snapshot["permit_denials"] == []

    await orchestrator.close()
    metrics_module.reset_for_test()
