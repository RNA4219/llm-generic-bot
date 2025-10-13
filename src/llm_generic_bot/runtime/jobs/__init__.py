from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Mapping, Optional

from ...core.cooldown import CooldownGate
from ...core.orchestrator import PermitEvaluator
from ...core.scheduler import Scheduler

JobFunc = Callable[[], Coroutine[Any, Any, Optional[str]]]


@dataclass(slots=True)
class JobContext:
    settings: Mapping[str, Any]
    scheduler: Scheduler
    platform: str
    default_channel: Optional[str]
    cooldown: CooldownGate
    permit: PermitEvaluator
    build_weather_post: Callable[..., Coroutine[Any, Any, Optional[str]]]
    build_news_post: Callable[..., Coroutine[Any, Any, Optional[str]]]
    build_omikuji_post: Callable[..., Coroutine[Any, Any, Optional[str]]]
    build_dm_digest: Callable[..., Coroutine[Any, Any, Optional[str]]]


@dataclass(slots=True)
class ScheduledJob:
    name: str
    func: JobFunc
    schedules: tuple[str, ...]
    channel: Optional[str]
    priority: int


__all__ = ["JobContext", "ScheduledJob", "JobFunc"]
