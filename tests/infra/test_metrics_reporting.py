"""Legacy shim for metrics reporting tests.

This module preserves backwards compatibility while the suite is migrated into
``tests/infra/metrics``. The checklist below tracks the split status to allow
incremental deletion once all call sites move to the new packages.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Final, Sequence

LEGACY_METRICS_REPORTING_SPLIT_CHECKLIST: Final[Sequence[str]] = (
    "[x] freeze_time フォールバック検証を tests/infra/metrics/test_reporting_freeze_time.py へ移行",
    "[x] RecordingMetrics スナップショット検証を tests/infra/metrics/test_reporting_recording_metrics.py へ移行",
    "[x] MetricsService/aggregator_state 連携検証を tests/infra/metrics/test_reporting_service.py へ移行",
)

_IMPORTED_MODULES: Final[tuple[ModuleType, ...]] = tuple(
    import_module(module_name)
    for module_name in (
        "tests.infra.metrics.test_reporting_freeze_time",
        "tests.infra.metrics.test_reporting_recording_metrics",
        "tests.infra.metrics.test_reporting_service",
    )
)

__all__ = ()
