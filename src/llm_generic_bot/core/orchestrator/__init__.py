from __future__ import annotations

import sys
from importlib import util
from pathlib import Path
from typing import TYPE_CHECKING, Any

__all__ = [
    "MetricsRecorder",
    "NullMetricsRecorder",
    "Orchestrator",
    "PermitDecision",
    "PermitDecisionLike",
    "PermitEvaluator",
    "Sender",
    "_SendRequest",
    "metrics_module",
    "processor",
]

_LEGACY_MODULE_NAME = "llm_generic_bot.core._legacy_orchestrator"
_LEGACY_MODULE_PATH = Path(__file__).resolve().parent.parent / "orchestrator.py"
_LEGACY_MODULE: Any | None = None


def _load_legacy_module() -> Any:
    global _LEGACY_MODULE
    if _LEGACY_MODULE is not None:
        return _LEGACY_MODULE
    spec = util.spec_from_file_location(_LEGACY_MODULE_NAME, _LEGACY_MODULE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - import error guard
        raise ImportError("failed to load legacy orchestrator module")
    module = util.module_from_spec(spec)
    sys.modules.setdefault(_LEGACY_MODULE_NAME, module)
    spec.loader.exec_module(module)
    _LEGACY_MODULE = module
    return module


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = _load_legacy_module()
        return getattr(module, name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


if TYPE_CHECKING:
    from ..orchestrator import (  # noqa: F401 - 型評価時の再公開
        MetricsRecorder,
        NullMetricsRecorder,
        Orchestrator,
        PermitDecision,
        PermitDecisionLike,
        PermitEvaluator,
        Sender,
        _SendRequest,
        metrics_module,
        processor,
    )


_LEGACY_BINDINGS = _load_legacy_module()
_LEGACY_BINDINGS.__dict__["__name__"] = __name__
for _name in __all__:
    try:
        globals()[_name] = getattr(_LEGACY_BINDINGS, _name)
    except AttributeError:
        continue

for _class_name in ("Orchestrator", "PermitDecision", "_SendRequest"):
    _cls = getattr(_LEGACY_BINDINGS, _class_name, None)
    if _cls is not None:
        setattr(_cls, "__module__", __name__)
