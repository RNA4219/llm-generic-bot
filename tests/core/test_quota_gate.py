from __future__ import annotations

from tests.core.quota_gate.test_basic_allow import *  # noqa: F401,F403
from tests.core.quota_gate.test_denial_metrics import *  # noqa: F401,F403
from tests.core.quota_gate.test_multitier import *  # noqa: F401,F403
from tests.core.quota_gate.test_reevaluation import *  # noqa: F401,F403
from tests.core.quota_gate.test_window_reset import *  # noqa: F401,F403

LEGACY_QUOTA_GATE_TEST_CHECKLIST = (
    "Confirm all quota gate tests run exclusively from tests/core/quota_gate/.",
    "Update imports to point to new modules and delete this shim.",
)

__all__ = ["LEGACY_QUOTA_GATE_TEST_CHECKLIST"]
