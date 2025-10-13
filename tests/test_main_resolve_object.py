from __future__ import annotations

import sys
from types import ModuleType

import pytest

from llm_generic_bot.main import _resolve_object


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str, module: ModuleType) -> None:
    monkeypatch.setitem(sys.modules, name, module)


def test_resolve_object_with_colon(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "tests.fake_module"
    module = ModuleType(module_name)
    nested = ModuleType(f"{module_name}.nested")
    expected: object = object()
    nested.target = expected  # type: ignore[attr-defined]
    module.nested = nested  # type: ignore[attr-defined]
    _install_module(monkeypatch, module_name, module)

    resolved = _resolve_object(f"{module_name}:nested.target")

    assert resolved is expected


def test_resolve_object_with_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "tests.dot_module"
    module = ModuleType(module_name)
    expected: object = object()
    module.target = expected  # type: ignore[attr-defined]
    _install_module(monkeypatch, module_name, module)

    resolved = _resolve_object(f"{module_name}.target")

    assert resolved is expected


def test_resolve_object_invalid_value() -> None:
    with pytest.raises(ValueError, match="invalid reference: invalid"):
        _resolve_object("invalid")
