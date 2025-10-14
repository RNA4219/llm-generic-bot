from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, cast

from ...config.quotas import QuotaSettings
from ...core.arbiter import PermitGate
from ...core.cooldown import CooldownGate
from ...core.dedupe import NearDuplicateFilter
from ...core.orchestrator import (
    PermitDecision,
    PermitDecisionLike,
    PermitEvaluator,
)
from ..jobs.common import get_float


def build_cooldown(cooldown_cfg: Mapping[str, Any]) -> CooldownGate:
    coeff_cfg = cooldown_cfg.get("coeff")
    coeff_mapping = coeff_cfg if isinstance(coeff_cfg, Mapping) else {}
    return CooldownGate(
        int(get_float(cooldown_cfg.get("window_sec"), 1800)),
        get_float(cooldown_cfg.get("mult_min"), 1.0),
        get_float(cooldown_cfg.get("mult_max"), 6.0),
        get_float(coeff_mapping.get("rate"), 0.5),
        get_float(coeff_mapping.get("time"), 0.8),
        get_float(coeff_mapping.get("eng"), 0.6),
    )


def build_dedupe(dedupe_cfg: Mapping[str, Any]) -> NearDuplicateFilter:
    return NearDuplicateFilter(
        k=int(get_float(dedupe_cfg.get("recent_k"), 20)),
        threshold=get_float(dedupe_cfg.get("sim_threshold"), 0.93),
    )


def build_permit(
    quota: QuotaSettings,
    *,
    permit_gate: Optional[PermitGate],
) -> PermitEvaluator:
    gate = permit_gate or (PermitGate(per_channel=quota.per_channel) if quota.per_channel else None)

    if gate is None:

        def _permit_no_gate(
            _platform: str, _channel: Optional[str], job: str
        ) -> PermitDecisionLike:
            return cast(PermitDecisionLike, PermitDecision.allow(job))

        return cast(PermitEvaluator, _permit_no_gate)

    def _permit_with_gate(platform: str, channel: Optional[str], job: str) -> PermitDecisionLike:
        decision = gate.permit(platform, channel, job)
        if decision.allowed:
            return cast(
                PermitDecisionLike,
                PermitDecision.allow(decision.job or job),
            )
        return cast(
            PermitDecisionLike,
            PermitDecision(
                allowed=False,
                reason=decision.reason,
                retryable=decision.retryable,
                job=decision.job or job,
            ),
        )

    return cast(PermitEvaluator, _permit_with_gate)
