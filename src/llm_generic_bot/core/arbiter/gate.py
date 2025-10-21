from __future__ import annotations

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Optional, Tuple

from llm_generic_bot.config.quotas import PerChannelQuotaConfig

from .models import (
    PERMIT_REEVALUATION_RETRY_SOURCE,
    PermitDecision,
    PermitGateConfig,
    PermitGateHooks,
    PermitQuotaLevel,
    PermitReevaluationOutcome,
    PermitRejectionContext,
)

DAY_SECONDS = 86400


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
        self._hooks = config.hooks if config else None
        if config is None:
            levels: Tuple[PermitQuotaLevel, ...] = (
                PermitQuotaLevel(name="per_channel", quota=per_channel),
            )
        else:
            levels = config.levels
        self._levels = levels
        self._history: Dict[str, Dict[Tuple[str, str], Deque[float]]] = {}
        self._tiers_by_level: Dict[str, tuple[_QuotaTier, ...]] = {}
        retention_candidates: list[int] = []
        for level in self._levels:
            tiers = self._resolve_tiers(level.quota)
            self._tiers_by_level[level.name] = tiers
            retention_candidates.extend(tier.window_seconds for tier in tiers)
        retention_window = max(retention_candidates) if retention_candidates else DAY_SECONDS
        self._retention_window = max(DAY_SECONDS, retention_window)

    def permit(
        self,
        platform: str,
        channel: Optional[str],
        job: Optional[str] = None,
    ) -> PermitDecision:
        now = self._time()
        pending: list[Deque[float]] = []
        for level in self._levels:
            key_a, key_b = level.key_fn(platform, channel, job)
            level_history = self._history.setdefault(level.name, {})
            history_key = (key_a, key_b)
            history = level_history.get(history_key)
            if history is None:
                history = deque()
                level_history[history_key] = history
            self._evict(history, now)
            for tier in self._tiers_by_level[level.name]:
                exceeded, retry_after = self._tier_state(history, now, tier)
                if exceeded:
                    return self._deny(
                        platform,
                        channel,
                        tier=tier,
                        job=job,
                        level=level.name,
                        retry_after=retry_after,
                    )
            pending.append(history)

        for history in pending:
            history.append(now)
        return PermitDecision(allowed=True, reason=None, retryable=True, job=job)

    def _resolve_tiers(self, quota: object) -> tuple[_QuotaTier, ...]:
        tiers_attr = getattr(quota, "tiers", None)
        if tiers_attr:
            return tuple(self._normalize_tier(tier) for tier in tiers_attr)
        burst_limit = getattr(quota, "burst_limit", None)
        window_seconds = getattr(quota, "window_seconds", None)
        day = getattr(quota, "day", None)
        if burst_limit is None or window_seconds is None or day is None:
            raise ValueError("quota must define tiers or burst/day limits")
        return (
            _QuotaTier(
                code="burst_limit",
                message="burst limit reached",
                retryable=True,
                limit=int(burst_limit),
                window_seconds=int(window_seconds),
                reevaluation=None,
            ),
            _QuotaTier(
                code="daily_limit",
                message="daily limit reached",
                retryable=False,
                limit=int(day),
                window_seconds=DAY_SECONDS,
                reevaluation=None,
            ),
        )

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

    def _tier_state(
        self, history: Deque[float], now: float, tier: _QuotaTier
    ) -> tuple[bool, Optional[float]]:
        cutoff = now - tier.window_seconds
        recent = [ts for ts in history if ts >= cutoff]
        exceeded = len(recent) >= tier.limit
        if not exceeded:
            return False, None
        threshold_index = len(recent) - tier.limit
        threshold_ts = recent[threshold_index]
        retry_after = tier.window_seconds - (now - threshold_ts)
        return True, max(0.0, retry_after)

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
        level: str,
        retry_after: Optional[float],
    ) -> PermitDecision:
        reevaluation_outcome: Optional[PermitReevaluationOutcome] = None
        if self._hooks and self._hooks.on_rejection:
            context = PermitRejectionContext(
                platform=platform,
                channel=channel,
                job=job,
                level=level,
                code=tier.code,
                message=tier.message,
            )
            reevaluation_outcome = self._hooks.on_rejection(context)
        reevaluation_value: PermitReevaluationOutcome | str | None
        if reevaluation_outcome is not None:
            reevaluation_value = reevaluation_outcome
        elif tier.reevaluation is not None:
            reevaluation_value = tier.reevaluation
        else:
            reevaluation_value = None
        tags = {
            "platform": platform or "-",
            "channel": channel or "-",
            "code": tier.code,
        }
        tags["level"] = level
        tags["retryable"] = "true" if tier.retryable else "false"
        tags["window_sec"] = str(tier.window_seconds)
        if retry_after is not None:
            tags["retry_after_sec"] = f"{retry_after:.0f}"
        if tier.reevaluation is not None:
            tags["reevaluation"] = tier.reevaluation
        else:
            reason_hint = tier.message
            if (
                reevaluation_outcome is not None
                and reevaluation_outcome.reason
            ):
                reason_hint = reevaluation_outcome.reason
            tags["reeval_reason"] = reason_hint
        retry_metadata: dict[str, str] | None = None
        reevaluation_hint: Optional[str] = None
        if isinstance(reevaluation_outcome, PermitReevaluationOutcome):
            reevaluation_hint = reevaluation_outcome.reason
        elif isinstance(tier.reevaluation, str):
            reevaluation_hint = tier.reevaluation
        if tier.reevaluation is not None or reevaluation_outcome is not None:
            retry_metadata = {
                "retry_source": PERMIT_REEVALUATION_RETRY_SOURCE,
                "permit_level": level,
            }
            if reevaluation_hint:
                retry_metadata["retry_reason"] = reevaluation_hint
        if self._metrics is not None:
            self._metrics("quota_denied", tags)
        self._logger.warning(
            "Quota denied for %s/%s at level %s: %s",
            platform or "-",
            channel or "-",
            level,
            tier.message,
        )
        return PermitDecision(
            allowed=False,
            reason=tier.message,
            retryable=tier.retryable,
            job=job,
            reevaluation=reevaluation_value,
            retry_after=retry_after,
            level=level,
            retry_metadata=retry_metadata,
        )


__all__ = ["DAY_SECONDS", "PermitGate"]
