from __future__ import annotations

import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Optional, Tuple

from llm_generic_bot.config.quotas import PerChannelQuotaConfig

DAY_SECONDS = 86400


KeyFn = Callable[[str, Optional[str], Optional[str]], Tuple[str, str]]


def _default_key(platform: str, channel: Optional[str], job: Optional[str]) -> Tuple[str, str]:
    del job
    return (platform or "-", channel or "-")


@dataclass(frozen=True)
class PermitReevaluationOutcome:
    level: str
    reason: str
    retry_after: Optional[float] = None
    allowed: Optional[bool] = None


@dataclass(frozen=True)
class PermitRejectionContext:
    platform: str
    channel: Optional[str]
    job: Optional[str]
    level: str
    code: str
    message: str


@dataclass(frozen=True)
class PermitGateHooks:
    on_rejection: Optional[Callable[[PermitRejectionContext], Optional[PermitReevaluationOutcome]]] = None


@dataclass(frozen=True)
class PermitQuotaLevel:
    name: str
    quota: PerChannelQuotaConfig
    key_fn: KeyFn = field(default=_default_key, repr=False)


@dataclass(frozen=True)
class PermitGateConfig:
    levels: Tuple[PermitQuotaLevel, ...]
    hooks: Optional[PermitGateHooks] = None


@dataclass(frozen=True)
class PermitDecision:
    allowed: bool
    reason: Optional[str]
    retryable: bool
    job: Optional[str] = None
    reevaluation: Optional[PermitReevaluationOutcome] = None


class PermitGate:
    def __init__(
        self,
        *,
        per_channel: PerChannelQuotaConfig,
        metrics: Optional[Callable[[str, Dict[str, str]], None]] = None,
        logger: Optional[logging.Logger] = None,
        time_fn: Optional[Callable[[], float]] = None,
        config: Optional[PermitGateConfig] = None,
    ) -> None:
        if config is not None and not config.levels:
            raise ValueError("PermitGateConfig.levels must not be empty")
        self.per_channel = per_channel
        self._metrics = metrics
        self._logger = logger or logging.getLogger(__name__)
        self._time = time_fn or time.time
        if config is None:
            levels: Tuple[PermitQuotaLevel, ...] = (
                PermitQuotaLevel(name="per_channel", quota=per_channel),
            )
            hooks = None
        else:
            levels = config.levels
            hooks = config.hooks
        self._levels = levels
        self._hooks = hooks
        self._history: Dict[Tuple[str, Tuple[str, str]], Deque[float]] = {}

    def permit(
        self,
        platform: str,
        channel: Optional[str],
        job: Optional[str] = None,
    ) -> PermitDecision:
        now = self._time()
        histories: list[Deque[float]] = []
        for level in self._levels:
            level_key = (level.name, level.key_fn(platform, channel, job))
            history = self._history.setdefault(level_key, deque())
            self._evict(history, now)

            if self._exceeds_burst(history, now, level.quota):
                return self._deny(
                    platform,
                    channel,
                    level=level.name,
                    code="burst_limit",
                    message="burst limit reached",
                    retryable=True,
                    job=job,
                )

            if self._exceeds_daily(history, level.quota):
                return self._deny(
                    platform,
                    channel,
                    level=level.name,
                    code="daily_limit",
                    message="daily limit reached",
                    retryable=False,
                    job=job,
                )

            histories.append(history)

        for history in histories:
            history.append(now)

        return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

    def _exceeds_burst(self, history: Deque[float], now: float, quota: PerChannelQuotaConfig) -> bool:
        window_start = now - quota.window_seconds
        count = sum(1 for ts in history if ts >= window_start)
        return count >= quota.burst_limit

    def _exceeds_daily(self, history: Deque[float], quota: PerChannelQuotaConfig) -> bool:
        count = len(history)
        return count >= quota.day

    def _evict(self, history: Deque[float], now: float) -> None:
        cutoff = now - DAY_SECONDS
        while history and history[0] < cutoff:
            history.popleft()

    def _deny(
        self,
        platform: str,
        channel: Optional[str],
        *,
        level: str,
        code: str,
        message: str,
        retryable: bool,
        job: Optional[str],
    ) -> PermitDecision:
        tags = {
            "platform": platform or "-",
            "channel": channel or "-",
            "code": code,
            "level": level,
            "reeval_reason": message,
        }
        reevaluation: Optional[PermitReevaluationOutcome] = None
        if self._hooks is not None and self._hooks.on_rejection is not None:
            context = PermitRejectionContext(
                platform=platform or "-",
                channel=channel,
                job=job,
                level=level,
                code=code,
                message=message,
            )
            reevaluation = self._hooks.on_rejection(context)
            if reevaluation is not None:
                tags["reeval_reason"] = reevaluation.reason
        if self._metrics is not None:
            self._metrics("quota_denied", tags)
        if reevaluation is not None:
            self._logger.warning(
                "Quota denied for %s/%s at level %s: %s (reeval=%s)",
                platform or "-",
                channel or "-",
                level,
                message,
                reevaluation.reason,
            )
        else:
            self._logger.warning(
                "Quota denied for %s/%s at level %s: %s",
                platform or "-",
                channel or "-",
                level,
                message,
            )
        return PermitDecision(
            allowed=False,
            reason=message,
            retryable=retryable,
            job=job,
            reevaluation=reevaluation,
        )


def jitter_seconds(jitter_range: Tuple[int, int]) -> int:
    lo, hi = jitter_range
    return random.randint(lo, hi)


def next_slot(ts: float, clash: bool, jitter_range: Tuple[int, int] = (60, 180)) -> float:
    if not clash:
        return ts
    return ts + jitter_seconds(jitter_range)
