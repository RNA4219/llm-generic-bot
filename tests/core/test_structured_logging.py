from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

structured_logging = importlib.import_module("tests.core.structured_logging")

LEGACY_STRUCTURED_LOGGING_SPLIT_CHECKLIST = structured_logging.LEGACY_STRUCTURED_LOGGING_SPLIT_CHECKLIST

_test_success = importlib.import_module("tests.core.structured_logging.test_success")
_test_failure = importlib.import_module("tests.core.structured_logging.test_failure")
_test_permit = importlib.import_module("tests.core.structured_logging.test_permit")
_test_duplicate = importlib.import_module("tests.core.structured_logging.test_duplicate")
_test_metrics = importlib.import_module("tests.core.structured_logging.test_metrics")

__all__ = ["LEGACY_STRUCTURED_LOGGING_SPLIT_CHECKLIST"]
