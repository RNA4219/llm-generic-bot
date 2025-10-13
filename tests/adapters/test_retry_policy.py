from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest

from llm_generic_bot.adapters.discord import DiscordSender
from llm_generic_bot.adapters.misskey import MisskeySender


class _FakeAsyncClient:
    def __init__(self, responses: list[Any]):
        self._responses = responses

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> None:
    def _factory(*args: object, **kwargs: object) -> _FakeAsyncClient:
        return _FakeAsyncClient(responses)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _make_response(status: int, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"), headers=headers)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("sender_factory", "adapter"),
    [
        (lambda: DiscordSender(token="t", channel_id="c"), "discord"),
        (lambda: MisskeySender(instance="misskey.test", token="t"), "misskey"),
    ],
)
@pytest.mark.anyio("asyncio")
async def test_retry_logging_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sender_factory: Callable[[], Any],
    adapter: str,
) -> None:
    responses: list[Any] = [
        _make_response(429, headers={"Retry-After": "1"}),
        _make_response(200),
    ]
    _install_fake_client(monkeypatch, responses)

    monkeypatch.setattr("uuid.uuid4", lambda: UUID(int=0))
    caplog.set_level("INFO")

    await sender_factory().send("payload")

    events = {"retry_scheduled", "send_success"}
    required_keys = {"event", "adapter", "correlation_id", "status_code", "attempt", "max_attempts", "target"}

    for record in caplog.records:
        payload = json.loads(record.msg)
        assert set(payload) >= required_keys
        assert payload["adapter"] == adapter
        assert payload["correlation_id"] == str(UUID(int=0))
        assert payload["event"] in events


@pytest.mark.parametrize(
    ("sender_factory", "adapter"),
    [
        (lambda: DiscordSender(token="t", channel_id="c"), "discord"),
        (lambda: MisskeySender(instance="misskey.test", token="t"), "misskey"),
    ],
)
@pytest.mark.anyio("asyncio")
async def test_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sender_factory: Callable[[], Any],
    adapter: str,
) -> None:
    responses: list[Any] = [
        _make_response(429, headers={"Retry-After": "5"}),
        _make_response(200),
    ]
    _install_fake_client(monkeypatch, responses)

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr("uuid.uuid4", lambda: UUID(int=0))
    caplog.set_level("INFO")

    await sender_factory().send("hello")

    assert sleep_calls == [5.0]
    record = json.loads(caplog.records[-1].msg)
    assert record["event"] == "send_success"
    assert record["correlation_id"] == str(UUID(int=0))
    assert record["adapter"] == adapter


@pytest.mark.parametrize(
    ("sender_factory", "adapter"),
    [
        (lambda: DiscordSender(token="t", channel_id="c"), "discord"),
        (lambda: MisskeySender(instance="misskey.test", token="t"), "misskey"),
    ],
)
@pytest.mark.anyio("asyncio")
async def test_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
    sender_factory: Callable[[], Any],
    adapter: str,
) -> None:
    responses: list[Any] = [
        _make_response(429),
        _make_response(429),
        _make_response(200),
    ]
    _install_fake_client(monkeypatch, responses)

    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr("uuid.uuid4", lambda: UUID(int=0))

    await sender_factory().send("hello")

    assert delays == [1.0, 2.0]


@pytest.mark.parametrize(
    "sender_factory",
    [lambda: DiscordSender(token="t", channel_id="c"), lambda: MisskeySender(instance="misskey.test", token="t")],
)
@pytest.mark.anyio("asyncio")
async def test_max_attempts(monkeypatch: pytest.MonkeyPatch, sender_factory: Callable[[], Any]) -> None:
    responses: list[Any] = [_make_response(503), _make_response(503), _make_response(503)]
    _install_fake_client(monkeypatch, responses)

    async def _fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr("uuid.uuid4", lambda: UUID(int=0))

    sender = sender_factory()
    with pytest.raises(httpx.HTTPStatusError):
        await sender.send("hello")


@pytest.mark.parametrize(
    "sender_factory",
    [lambda: DiscordSender(token="t", channel_id="c"), lambda: MisskeySender(instance="misskey.test", token="t")],
)
@pytest.mark.anyio("asyncio")
async def test_non_retryable(monkeypatch: pytest.MonkeyPatch, sender_factory: Callable[[], Any]) -> None:
    responses: list[Any] = [_make_response(400)]
    _install_fake_client(monkeypatch, responses)
    sender = sender_factory()

    with pytest.raises(httpx.HTTPStatusError):
        await sender.send("hello")


