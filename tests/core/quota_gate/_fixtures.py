from __future__ import annotations

from dataclasses import dataclass


class DummyMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def increment(self, name: str, tags: dict[str, str]) -> None:
        self.calls.append((name, tags))


@dataclass(frozen=True)
class _FakeQuotaTier:
    code: str
    limit: int
    window_minutes: int
    message: str
    retryable: bool
    reevaluation: str

    @property
    def window_seconds(self) -> int:
        return self.window_minutes * 60


@dataclass(frozen=True)
class _FakeQuotaConfig:
    tiers: tuple[_FakeQuotaTier, ...]


__all__ = ["DummyMetrics", "_FakeQuotaTier", "_FakeQuotaConfig"]
