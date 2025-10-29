import asyncio
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from llm_generic_bot.core.cooldown import CooldownGate
from llm_generic_bot.core.dedupe import NearDuplicateFilter
from llm_generic_bot.core.orchestrator import processor, runtime


class _PermitDecision:
    allowed = True
    reason = None
    retryable = True
    job = "job"
    retry_after = None
    level = None
    reevaluation = None


class _NoopSender:
    async def send(self, text: str, channel: str | None = None, *, job: str | None = None) -> None:
        raise AssertionError("send should not be called in this test")


def _permit(platform: str, channel: str | None, job: str) -> _PermitDecision:
    return _PermitDecision()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_retry_cleanup_reraises_cancelled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = MagicMock()
    orchestrator = runtime.Orchestrator(
        sender=_NoopSender(),
        cooldown=CooldownGate(60, 1.0, 1.0, 0.0, 0.0, 0.0),
        dedupe=NearDuplicateFilter(),
        permit=_permit,
        metrics=None,
        logger=logger,
    )

    request = runtime._SendRequest(
        text="hello",
        job="job",
        platform="test",
        channel=None,
        correlation_id="cid",
    )
    directive = processor.RetryDirective(retry_after=0.1, reason=None, allowed=None)

    class _FakeTask:
        def __init__(self) -> None:
            self._callback: Callable[[asyncio.Task[None]], None] | None = None
            self._cancelled = False

        def add_done_callback(self, callback: Callable[[asyncio.Task[None]], None]) -> None:
            self._callback = callback

        def result(self) -> None:
            if self._cancelled:
                raise asyncio.CancelledError
            return None

        def cancel(self) -> None:
            self._cancelled = True

        def __await__(self):
            if self._cancelled:
                raise asyncio.CancelledError
            if False:
                yield  # pragma: no cover - generator required for await protocol
            return None

        def __hash__(self) -> int:
            return id(self)

    fake_task = _FakeTask()

    def _create_task_and_discard(coro: object) -> _FakeTask:
        if hasattr(coro, "close"):
            coro.close()
        return fake_task

    with monkeypatch.context() as patcher:
        patcher.setattr(asyncio, "create_task", _create_task_and_discard)
        orchestrator._schedule_retry(request, directive)

    callback = fake_task._callback
    assert callback is not None

    fake_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        callback(fake_task)  # type: ignore[arg-type]

    assert not logger.exception.called

    await orchestrator.close()
