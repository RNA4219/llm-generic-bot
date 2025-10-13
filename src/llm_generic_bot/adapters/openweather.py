from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, cast

import httpx

_OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_DEFAULT_TIMEOUT = 20.0
_shared_client: httpx.AsyncClient | None = None
_shared_client_lock: asyncio.Lock | None = None


def _create_client(*, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


async def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client, _shared_client_lock
    if _shared_client is not None:
        return _shared_client

    if _shared_client_lock is None:
        _shared_client_lock = asyncio.Lock()

    async with _shared_client_lock:
        if _shared_client is None:
            _shared_client = _create_client(timeout=_DEFAULT_TIMEOUT)

    assert _shared_client is not None
    return _shared_client


@asynccontextmanager
async def _resolve_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return

    shared = await _get_shared_client()
    try:
        yield shared
    finally:
        # The shared client is kept alive for reuse.
        pass


async def _reset_shared_client() -> None:
    global _shared_client, _shared_client_lock
    if _shared_client is not None:
        await _shared_client.aclose()
    _shared_client = None
    _shared_client_lock = None


async def fetch_current_city(
    city: str,
    api_key: str | None = None,
    *,
    units: str = "metric",
    lang: str = "ja",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    api_key = api_key or os.getenv("OPENWEATHER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENWEATHER_API_KEY missing")

    params = {"q": city, "appid": api_key, "units": units, "lang": lang}

    async with _resolve_client(client) as resolved:
        response = await resolved.get(_OPENWEATHER_URL, params=params)

    response.raise_for_status()
    payload = response.json()
    return cast(dict[str, Any], payload)
