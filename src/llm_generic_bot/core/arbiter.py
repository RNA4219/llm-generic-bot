from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

_package_dir = Path(__file__).with_name("arbiter")
__path__ = [str(_package_dir)]  # type: ignore[var-annotated]

_gate = importlib.import_module(".arbiter.gate", __package__)
_models = importlib.import_module(".arbiter.models", __package__)
_jitter = importlib.import_module(".arbiter.jitter", __package__)

gate = _gate
models = _models
jitter = _jitter

DAY_SECONDS = _gate.DAY_SECONDS
PermitGate = _gate.PermitGate

KeyFn = _models.KeyFn
PermitDecision = _models.PermitDecision
PermitGateConfig = _models.PermitGateConfig
PermitGateHooks = _models.PermitGateHooks
PermitQuotaLevel = _models.PermitQuotaLevel
PermitReevaluationOutcome = _models.PermitReevaluationOutcome
PermitRejectionContext = _models.PermitRejectionContext

jitter_seconds = _jitter.jitter_seconds
next_slot: Callable[[float, bool, tuple[int, int]], float] = _jitter.next_slot


def permit_decision(
    *,
    allowed: bool,
    reason: str | None,
    retryable: bool,
    job: str | None = None,
    reevaluation: PermitReevaluationOutcome | str | None = None,
    retry_after: float | None = None,
    level: str | None = None,
) -> PermitDecision:
    """Create a :class:`PermitDecision` with explicit retry context."""

    return PermitDecision(
        allowed=allowed,
        reason=reason,
        retryable=retryable,
        job=job,
        reevaluation=reevaluation,
        retry_after=retry_after,
        level=level,
    )

LEGACY_PERMIT_GATE_REFACTOR_CHECKLIST = (
    "- [ ] すべての呼び出しサイトを llm_generic_bot.core.arbiter.gate へ更新",
    "- [ ] PermitGate 関連ドキュメントを新ディレクトリ構成へ更新",
    "- [ ] 互換レイヤー撤去前に pytest/mypy/ruff 緑化を再確認",
)

__all__ = [
    "DAY_SECONDS",
    "KeyFn",
    "LEGACY_PERMIT_GATE_REFACTOR_CHECKLIST",
    "PermitDecision",
    "PermitGate",
    "PermitGateConfig",
    "PermitGateHooks",
    "PermitQuotaLevel",
    "PermitReevaluationOutcome",
    "PermitRejectionContext",
    "gate",
    "permit_decision",
    "jitter",
    "jitter_seconds",
    "models",
    "next_slot",
]
