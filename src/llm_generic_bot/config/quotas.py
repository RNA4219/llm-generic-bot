from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class PerChannelQuotaConfig:
    day: int
    window_minutes: int
    burst_limit: int

    @property
    def window_seconds(self) -> int:
        return self.window_minutes * 60


@dataclass(frozen=True)
class QuotaSettings:
    per_channel: Optional[PerChannelQuotaConfig]


def _ensure_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"quota.{field} must be a positive integer")
    return value


def load_quota_settings(settings: Mapping[str, Any]) -> QuotaSettings:
    quota_block = settings.get("quota")
    if quota_block is None:
        return QuotaSettings(per_channel=None)
    if not isinstance(quota_block, Mapping):
        raise ValueError("quota must be a mapping")

    per_channel_raw = quota_block.get("per_channel")
    if per_channel_raw is None:
        return QuotaSettings(per_channel=None)
    if not isinstance(per_channel_raw, Mapping):
        raise ValueError("quota.per_channel must be a mapping")

    day = _ensure_positive_int(per_channel_raw.get("day"), "per_channel.day")
    window_min = _ensure_positive_int(per_channel_raw.get("window_min"), "per_channel.window_min")
    burst_limit = _ensure_positive_int(per_channel_raw.get("burst_limit"), "per_channel.burst_limit")

    return QuotaSettings(
        per_channel=PerChannelQuotaConfig(day=day, window_minutes=window_min, burst_limit=burst_limit)
    )
