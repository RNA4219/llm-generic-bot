"""LEGACY SHIM for runtime multicontent tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# LEGACY_RUNTIME_MULTICONTENT_CHECKLIST:
# - [ ] Replace legacy shim with direct package discovery once migration completes.

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytestmark = pytest.mark.anyio("asyncio")

from tests.integration.runtime_multicontent.conftest import anyio_backend  # noqa: F401,E402
from tests.integration.runtime_multicontent.test_dm_digest import *  # noqa: F401,F403,E402
from tests.integration.runtime_multicontent.test_pipeline import *  # noqa: F401,F403,E402
from tests.integration.runtime_multicontent.test_providers import *  # noqa: F401,F403,E402

__all__ = [name for name in globals() if name.startswith("test_")]
