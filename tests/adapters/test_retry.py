from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from llm_generic_bot.adapters._retry import RetryConfig, run_with_retry


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_run_with_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _attempt() -> httpx.Response:
        return httpx.Response(200, request=httpx.Request("GET", "https://example.invalid"))

    async def _fail_sleep(delay: float) -> None:  # pragma: no cover - should not be called
        raise AssertionError(f"unexpected sleep: {delay}")

    monkeypatch.setattr(asyncio, "sleep", _fail_sleep)
    logger = logging.getLogger("test.retry")

    response = await run_with_retry(
        adapter="test-adapter",
        correlation_id="cid",
        target="https://example.invalid",
        attempt=_attempt,
        retry_config=RetryConfig(max_attempts=3),
        logger=logger,
    )

    assert response.status_code == 200
