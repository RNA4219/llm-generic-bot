from __future__ import annotations

import asyncio
import sys
import types
from aiohttp import web

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

# Global state for health check
_health_state = {"status": "starting", "scheduler_running": False}


async def health_handler(request: web.Request) -> web.Response:
    """Health check endpoint."""
    if _health_state["status"] == "running":
        return web.json_response({"status": "healthy", **_health_state})
    return web.json_response({"status": _health_state["status"]}, status=503)


async def start_health_server(port: int = 8080) -> web.AppRunner:
    """Start HTTP server for health checks."""
    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner


async def main() -> None:
    port = 8080
    _health_state["status"] = "initializing"

    health_runner = await start_health_server(port)
    _health_state["status"] = "running"

    try:
        scheduler, orchestrator, _ = setup_runtime(Settings("config/settings.json").data)
        _health_state["scheduler_running"] = True
        try:
            await scheduler.run_forever()
        finally:
            await orchestrator.close()
    finally:
        _health_state["status"] = "stopping"
        await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())