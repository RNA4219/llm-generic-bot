from __future__ import annotations

import asyncio

import pytest

import llm_generic_bot.infra.metrics.aggregator_state as aggregator_state_module
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


def test_setup_runtime_applies_scheduler_jitter_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
        "arbiter": {"jitter_sec": [10, 40]},
    }

    scheduler, orchestrator, _ = setup_runtime(settings)

    assert scheduler.jitter_range == (10, 40)
    asyncio.run(orchestrator.close())


def test_setup_runtime_rejects_non_sequence_scheduler_jitter_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
        "arbiter": {"jitter_sec": {10, 40}},
    }

    with pytest.raises(ValueError):
        setup_runtime(settings)


def test_setup_runtime_rejects_invalid_scheduler_jitter_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    settings = {
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
        "arbiter": {"jitter_sec": [0, 40]},
    }

    with pytest.raises(ValueError):
        setup_runtime(settings)


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
    assert aggregator_state_module._AGGREGATOR.backend_configured is False

    generated_at = snapshot["generated_at"]
    assert generated_at.endswith("+00:00")
    assert snapshot == {
        "generated_at": generated_at,
        "success_rate": {},
        "latency_histogram_seconds": {},
        "permit_denials": [],
    }

    await orchestrator.close()
    metrics_module.reset_for_test()


@pytest.mark.anyio("asyncio")
async def test_setup_runtime_resets_metrics_state_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics_module.reset_for_test()
    monkeypatch.setattr(
        "llm_generic_bot.core.orchestrator.Orchestrator._start_worker",
        lambda self: None,
    )
    enabled_settings = {
        "metrics": {"enabled": True, "backend": "memory"},
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
    }

    _, orchestrator_enabled, _ = setup_runtime(enabled_settings)

    await metrics_module.report_send_success(
        job="news",
        platform="discord",
        channel="#bot",
        duration_seconds=1.0,
        permit_tags=None,
    )
    snapshot_before_disable = metrics_module.weekly_snapshot()
    assert snapshot_before_disable["success_rate"] != {}

    await orchestrator_enabled.close()

    disabled_settings = {
        "metrics": {"enabled": False},
        "profiles": {
            "discord": {"enabled": True, "channel": "#bot"},
            "misskey": {"enabled": False},
        },
    }

    _, orchestrator_disabled, _ = setup_runtime(disabled_settings)

    snapshot_after_disable = metrics_module.weekly_snapshot()
    assert snapshot_after_disable["success_rate"] == {}
    assert snapshot_after_disable["latency_histogram_seconds"] == {}
    assert snapshot_after_disable["permit_denials"] == []

    await orchestrator_disabled.close()
    metrics_module.reset_for_test()
