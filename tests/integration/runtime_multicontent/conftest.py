from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from llm_generic_bot.features.dm_digest import DigestLogEntry
from llm_generic_bot.features.news import NewsFeedItem

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _ensure_sample_providers() -> None:
    module_name = "llm_generic_bot.runtime.providers"
    if module_name in sys.modules:
        return

    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError:
        providers_module = ModuleType(module_name)

        async def _sample_fetch(_url: str, *, limit: int | None = None) -> list[NewsFeedItem]:
            del limit
            return []

        async def _sample_summarize(item: NewsFeedItem, *, language: str = "ja") -> str:
            del language
            return item.summary or item.title

        async def _sample_collect(_channel: str, *, limit: int) -> list[DigestLogEntry]:
            del _channel, limit
            return []

        async def _sample_digest(text: str, *, max_events: int | None = None) -> str:
            del text, max_events
            return ""

        async def _sample_send(
            text: str,
            channel: str | None = None,
            *,
            correlation_id: str | None = None,
            job: str | None = None,
            recipient_id: str | None = None,
        ) -> None:
            del text, channel, correlation_id, job, recipient_id
            return None

        provider_fixtures = {
            "SAMPLE_NEWS_FEED": SimpleNamespace(fetch=_sample_fetch),
            "SAMPLE_NEWS_SUMMARY": SimpleNamespace(summarize=_sample_summarize),
            "SAMPLE_DM_LOG": SimpleNamespace(collect=_sample_collect),
            "SAMPLE_DM_SUMMARY": SimpleNamespace(summarize=_sample_digest),
            "SAMPLE_DM_SENDER": SimpleNamespace(send=_sample_send),
        }

        for attr, value in provider_fixtures.items():
            setattr(providers_module, attr, value)

        sys.modules[module_name] = providers_module


_ensure_sample_providers()
