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


@dataclass(frozen=True)
class _QuotaTier:
    code: str
    message: str
    retryable: bool
    limit: int
    window_seconds: int
    reevaluation: Optional[str]


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
        self._history: Dict[Tuple[str, str], Deque[float]] = {}
        tiers_attr = getattr(per_channel, "tiers", None)
        if tiers_attr:
            normalized_tiers = tuple(self._normalize_tier(tier) for tier in tiers_attr)
        else:
            normalized_tiers = (
                _QuotaTier(
                    code="burst_limit",
                    message="burst limit reached",
                    retryable=True,
                    limit=per_channel.burst_limit,
                    window_seconds=per_channel.window_seconds,
                    reevaluation=None,
                ),
                _QuotaTier(
                    code="daily_limit",
                    message="daily limit reached",
                    retryable=False,
                    limit=per_channel.day,
                    window_seconds=DAY_SECONDS,
                    reevaluation=None,
                ),
            )
        self._tiers: tuple[_QuotaTier, ...] = normalized_tiers
        retention_candidates = [tier.window_seconds for tier in self._tiers]
        retention_window = max(retention_candidates) if retention_candidates else DAY_SECONDS
        self._retention_window = max(DAY_SECONDS, retention_window)

    def permit(
        self,
        platform: str,
        channel: Optional[str],
        job: Optional[str] = None,
    ) -> PermitDecision:
        now = self._time()
        key = _default_key(platform, channel, job)
        history = self._history.setdefault(key, deque())
        self._evict(history, now)
        for tier in self._tiers:
            if self._exceeds_tier(history, now, tier):
                return self._deny(platform, channel, tier=tier, job=job)

        history.append(now)
        return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

    def _normalize_tier(self, tier: object) -> _QuotaTier:
        code = getattr(tier, "code", None)
        if not code:
            raise ValueError("quota tier must define a code")

        limit = getattr(tier, "limit", None)
        if limit is None:
            limit = getattr(tier, "burst_limit", None)
        if limit is None:
            raise ValueError(f"quota tier {code} must define a positive limit")
        limit_value = int(limit)
        if limit_value <= 0:
            raise ValueError(f"quota tier {code} limit must be positive")

        window_seconds = getattr(tier, "window_seconds", None)
        if window_seconds is None:
            window_minutes = getattr(tier, "window_minutes", None)
            if window_minutes is not None:
                window_seconds = int(window_minutes) * 60
        if window_seconds is None:
            window_seconds = DAY_SECONDS
        window_value = int(window_seconds)
        if window_value <= 0:
            raise ValueError(f"quota tier {code} window must be positive")

        message = getattr(tier, "message", None) or code
        retryable_attr = getattr(tier, "retryable", True)
        retryable = bool(retryable_attr)
        reevaluation = getattr(tier, "reevaluation", None)
        if reevaluation is None:
            reevaluation = getattr(tier, "reevaluation_tag", None)

        return _QuotaTier(
            code=str(code),
            message=str(message),
            retryable=retryable,
            limit=limit_value,
            window_seconds=window_value,
            reevaluation=str(reevaluation) if reevaluation is not None else None,
        )

    def _exceeds_tier(self, history: Deque[float], now: float, tier: _QuotaTier) -> bool:
        cutoff = now - tier.window_seconds
        count = sum(1 for ts in history if ts >= cutoff)
        return count >= tier.limit

    def _evict(self, history: Deque[float], now: float) -> None:
        cutoff = now - self._retention_window
        while history and history[0] < cutoff:
            history.popleft()

    def _deny(
        self,
        platform: str,
        channel: Optional[str],
        *,
        tier: _QuotaTier,
        job: Optional[str],
    ) -> PermitDecision:
        tags = {
            "platform": platform or "-",
            "channel": channel or "-",
            "code": tier.code,
        }
        if tier.reevaluation is not None:
            tags["reevaluation"] = tier.reevaluation
        if self._metrics is not None:
            self._metrics("quota_denied", tags)
        self._logger.warning(
            "Quota denied for %s/%s: %s",
            platform or "-",
            channel or "-",
            tier.message,
        )
        reevaluation = tier.reevaluation
        return PermitDecision(
            allowed=False,
            reason=tier.message,
            retryable=tier.retryable,
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
