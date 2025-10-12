from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from llm_generic_bot.core.orchestrator import PermitDecision
from llm_generic_bot.features.dm_digest import DigestLogEntry, build_dm_digest

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class Scenario:
    name: str
    cfg: dict[str, Any]
    entries: list[DigestLogEntry]
    summary: str
    expected: str | None
    permit_return: Callable[[str, str | None, str], PermitDecision]
    expect_retry: bool


def _allowed(*_: object) -> PermitDecision:
    return PermitDecision.allowed("dm_digest")


SCENARIOS = (
    Scenario(
        name="digest_success_with_retry",
        cfg={
            "source_channel": "123",
            "recipient_id": "user-42",
            "job": "digest",
            "header": "Daily Digest",
            "max_events": 5,
        },
        entries=[
            DigestLogEntry(datetime(2024, 4, 1, 12, 0, tzinfo=timezone.utc), "INFO", "first"),
            DigestLogEntry(datetime(2024, 4, 1, 13, 0, tzinfo=timezone.utc), "ERROR", "second"),
        ],
        summary="まとめ",
        expected="Daily Digest\nまとめ",
        permit_return=lambda platform, channel, job: PermitDecision.allowed(job),
        expect_retry=True,
    ),
    Scenario(
        name="digest_no_entries",
        cfg={
            "source_channel": "123",
            "recipient_id": "user-42",
            "job": "digest",
            "header": "Daily Digest",
            "max_events": 5,
        },
        entries=[],
        summary="",
        expected=None,
        permit_return=_allowed,
        expect_retry=False,
    ),
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_build_dm_digest_flow(scenario: Scenario, caplog: pytest.LogCaptureFixture) -> None:
    collected: list[tuple[str, int]] = []

    async def collect(channel: str, *, limit: int) -> list[DigestLogEntry]:
        collected.append((channel, limit))
        return scenario.entries

    summary_inputs: list[str] = []

    async def summarize(text: str, *, max_events: int | None = None) -> str:
        summary_inputs.append(text)
        assert max_events == scenario.cfg.get("max_events")
        return scenario.summary

    send_calls: list[dict[str, Any]] = []
    attempts = 0

    async def send(
        text: str,
        channel: str | None = None,
        *,
        correlation_id: str | None = None,
        job: str | None = None,
        recipient_id: str | None = None,
    ) -> None:
        nonlocal attempts
        send_calls.append(
            {
                "text": text,
                "channel": channel,
                "job": job,
                "recipient_id": recipient_id,
                "correlation_id": correlation_id,
            }
        )
        attempts += 1
        if scenario.expect_retry and attempts == 1:
            raise RuntimeError("transient")

    permit_calls: list[tuple[str, str | None, str]] = []

    def permit(platform: str, channel: str | None, job: str) -> PermitDecision:
        permit_calls.append((platform, channel, job))
        return scenario.permit_return(platform, channel, job)

    caplog.set_level(logging.INFO)

    result = await build_dm_digest(
        scenario.cfg,
        log_provider=SimpleNamespace(collect=collect),
        summarizer=SimpleNamespace(summarize=summarize),
        sender=SimpleNamespace(send=send),
        permit=permit,
        logger=logging.getLogger(f"test.dm_digest.{scenario.name}"),
    )

    assert result == scenario.expected
    assert collected == [(scenario.cfg["source_channel"], scenario.cfg.get("max_events", 50))]

    if scenario.entries:
        assert len(summary_inputs) == 1
        for entry in scenario.entries:
            assert entry.message in summary_inputs[0]
        assert permit_calls == [("discord_dm", scenario.cfg["recipient_id"], scenario.cfg["job"])]
        expected_attempts = 2 if scenario.expect_retry else 1
        assert len(send_calls) == expected_attempts
        assert all(call["recipient_id"] == scenario.cfg["recipient_id"] for call in send_calls)
        assert send_calls[-1]["text"] == scenario.expected
        if scenario.expect_retry:
            assert any("dm_digest_retry" in record.message for record in caplog.records)
    else:
        assert not summary_inputs
        assert not permit_calls
        assert not send_calls
        assert any("dm_digest_skip_empty" in record.message for record in caplog.records)
