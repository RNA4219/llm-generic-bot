from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock

import httpx
import pytest

from llm_generic_bot.adapters import openweather


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

class _DummyResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - interface compatibility
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _DummyClient:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, params: dict[str, Any]) -> _DummyResponse:
        self.calls.append((url, params))
        return _DummyResponse({"city": params["q"]})

    async def aclose(self) -> None:  # pragma: no cover - compatibility
        return None


@pytest.mark.anyio("asyncio")
async def test_fetch_current_city_reuses_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWEATHER_API_KEY", "token")
    await openweather._reset_shared_client()

    dummy_clients: list[_DummyClient] = []

    def _factory(*, timeout: float) -> _DummyClient:
        client = _DummyClient(timeout=timeout)
        dummy_clients.append(client)
        return client

    monkeypatch.setattr(openweather, "_create_client", _factory)

    first = await openweather.fetch_current_city("Tokyo")
    second = await openweather.fetch_current_city("Osaka")

    assert first == {"city": "Tokyo"}
    assert second == {"city": "Osaka"}
    assert len(dummy_clients) == 1
    client = dummy_clients[0]
    assert client.calls[0][1]["q"] == "Tokyo"
    assert client.calls[1][1]["q"] == "Osaka"


def _timeout_error() -> Exception:
    return httpx.TimeoutException("boom")

def _http_error() -> Exception:
    request = httpx.Request("GET", "https://api.openweathermap.org/data/2.5/weather")
    response = httpx.Response(500, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


@pytest.mark.anyio("asyncio")
@pytest.mark.parametrize(
    "error_factory",
    [_timeout_error, _http_error],
)
async def test_fetch_current_city_delegates_errors_to_retry_wrapper(
    monkeypatch: pytest.MonkeyPatch, error_factory: Callable[[], Exception]
) -> None:
    monkeypatch.setenv("OPENWEATHER_API_KEY", "token")

    client = AsyncMock(spec=httpx.AsyncClient)
    side_effect = error_factory()
    client.get.side_effect = side_effect

    with pytest.raises(type(side_effect)):
        await openweather.fetch_current_city("Tokyo", client=client)

    client.get.assert_awaited()
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": "Tokyo",
        "appid": "token",
        "units": "metric",
        "lang": "ja",
    }
    client.get.assert_called_with(url, params=params)
