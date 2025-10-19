from __future__ import annotations

import logging
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Mapping, Optional, Tuple

from llm_generic_bot.config.quotas import PerChannelQuotaConfig

DAY_SECONDS = 86400


@dataclass(frozen=True)
class PermitDecision:
    allowed: bool
    reason: Optional[str]
    retryable: bool
    job: Optional[str] = None


class PermitGate:
    def __init__(
        self,
        *,
        per_channel: Optional[PerChannelQuotaConfig],
        tiers: Optional[Mapping[str, PerChannelQuotaConfig]] = None,
        metrics: Optional[Callable[[str, Dict[str, str]], None]] = None,
        logger: Optional[logging.Logger] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.per_channel = per_channel
        self._tiers: Dict[str, PerChannelQuotaConfig] = dict(tiers) if tiers else {}
        self._metrics = metrics
        self._logger = logger or logging.getLogger(__name__)
        self._time = time_fn or time.time
        self._history: Dict[Tuple[str, ...], Deque[float]] = {}

    def permit(
        self,
        platform: str,
        channel: Optional[str],
        job: Optional[str] = None,
    ) -> PermitDecision:
        config, key = self._resolve_quota(platform, channel, job)
        if config is None:
            return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

        history = self._history.setdefault(key, deque())
        now = self._time()
        self._evict(history, now)

        if self._exceeds_burst(history, now, config):
            return self._deny(
                platform,
                channel,
                code="burst_limit",
                message="burst limit reached",
                retryable=True,
                job=job,
            )

        if self._exceeds_daily(history, config):
            return self._deny(
                platform,
                channel,
                code="daily_limit",
                message="daily limit reached",
                retryable=False,
                job=job,
            )

        history.append(now)
        return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

    def _exceeds_burst(
        self,
        history: Deque[float],
        now: float,
        config: PerChannelQuotaConfig,
    ) -> bool:
        window_start = now - config.window_seconds
        count = sum(1 for ts in history if ts >= window_start)
        return count >= config.burst_limit

    def _exceeds_daily(
        self,
        history: Deque[float],
        config: PerChannelQuotaConfig,
    ) -> bool:
        count = len(history)
        return count >= config.day

    def _evict(self, history: Deque[float], now: float) -> None:
        cutoff = now - DAY_SECONDS
        while history and history[0] < cutoff:
            history.popleft()

    def _deny(
        self,
        platform: str,
        channel: Optional[str],
        *,
        code: str,
        message: str,
        retryable: bool,
        job: Optional[str],
    ) -> PermitDecision:
        tags = {
            "platform": platform or "-",
            "channel": channel or "-",
            "code": code,
        }
        if self._metrics is not None:
            self._metrics("quota_denied", tags)
        self._logger.warning(
            "Quota denied for %s/%s: %s", platform or "-", channel or "-", message
        )
        return PermitDecision(
            allowed=False,
            reason=message,
            retryable=retryable,
            job=job,
        )

    def _resolve_quota(
        self,
        platform: str,
        channel: Optional[str],
        job: Optional[str],
    ) -> tuple[Optional[PerChannelQuotaConfig], Tuple[str, ...]]:
        base_key = (platform or "-", channel or "-")
        if job:
            tier = self._tiers.get(job)
            if tier is not None:
                return tier, base_key + (job,)
        if self.per_channel is None:
            return None, base_key
        return self.per_channel, base_key


def jitter_seconds(jitter_range: Tuple[int, int]) -> int:
    lo, hi = jitter_range
    return random.randint(lo, hi)


def next_slot(ts: float, clash: bool, jitter_range: Tuple[int, int] = (60, 180)) -> float:
    if not clash:
        return ts
    return ts + jitter_seconds(jitter_range)
