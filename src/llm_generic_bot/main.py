from __future__ import annotations

import asyncio
import sys
import types

from .config.loader import Settings
from .runtime import setup as runtime_setup_module
from .runtime.setup import _resolve_object, setup_runtime

__all__ = [
    "setup_runtime",
    "main",
    "_resolve_object",
    "build_weather_post",
    "build_news_post",
    "build_dm_digest",
    "build_omikuji_post",
]

_FORWARDED_NAMES = {
    "build_weather_post",
    "build_news_post",
    "build_dm_digest",
    "build_omikuji_post",
}


class _MainModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:  # pragma: no cover - module proxy
        if name in _FORWARDED_NAMES:
            setattr(runtime_setup_module, name, value)
        super().__setattr__(name, value)


_module = sys.modules[__name__]
if not isinstance(_module, _MainModule):
    _module.__class__ = _MainModule

build_weather_post = runtime_setup_module.build_weather_post
build_news_post = runtime_setup_module.build_news_post
build_dm_digest = runtime_setup_module.build_dm_digest
build_omikuji_post = runtime_setup_module.build_omikuji_post


async def main() -> None:
    scheduler, orchestrator, _ = setup_runtime(Settings("config/settings.json").data)
    try:
        await scheduler.run_forever()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
