from __future__ import annotations

from .orchestrator_send import (
    test_duplicate_flow as duplicate_flow_module,
    test_exception_flow as exception_flow_module,
    test_permit_denied_flow as permit_denied_flow_module,
    test_success_flow as success_flow_module,
)
from .orchestrator_send.conftest import DummySender, _capture_events

LEGACY_ORCHESTRATOR_SEND_SPLIT_CHECKLIST = [
    "[x] tests/core/orchestrator_send/ へ分割済み",
    "[x] DummySender/_capture_events を共有フィクスチャに移設済み",
    "[x] 新ディレクトリで pytest 実行を確認済み",
    "[x] 例外フローテストを追加済み",
]

__all__ = [
    "LEGACY_ORCHESTRATOR_SEND_SPLIT_CHECKLIST",
    "DummySender",
    "_capture_events",
    "duplicate_flow_module",
    "exception_flow_module",
    "permit_denied_flow_module",
    "success_flow_module",
]
