from __future__ import annotations

from . import aggregator as _aggregator

configure_backend = _aggregator.configure_backend
report_permit_denied = _aggregator.report_permit_denied
report_send_failure = _aggregator.report_send_failure
report_send_success = _aggregator.report_send_success
reset_for_test = _aggregator.reset_for_test
set_retention_days = _aggregator.set_retention_days
weekly_snapshot = _aggregator.weekly_snapshot
_utcnow = _aggregator._utcnow

__all__ = [
    "configure_backend",
    "report_permit_denied",
    "report_send_failure",
    "report_send_success",
    "reset_for_test",
    "set_retention_days",
    "weekly_snapshot",
]
