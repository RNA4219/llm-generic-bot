from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Tuple

from llm_generic_bot.config.quotas import PerChannelQuotaConfig

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


PERMIT_REEVALUATION_RETRY_SOURCE = "permit_reevaluation"


@dataclass(frozen=True)
class PermitDecision:
    allowed: bool
    reason: Optional[str]
    retryable: bool
    job: Optional[str] = None
    reevaluation: PermitReevaluationOutcome | str | None = None
    retry_after: Optional[float] = None
    level: Optional[str] = None
    retry_metadata: Mapping[str, str] | None = None


__all__ = [
    "KeyFn",
    "PERMIT_REEVALUATION_RETRY_SOURCE",
    "PermitDecision",
    "PermitGateConfig",
    "PermitGateHooks",
    "PermitQuotaLevel",
    "PermitReevaluationOutcome",
    "PermitRejectionContext",
]
