from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .cache import clamp_unit_interval, coerce_float


@dataclass(frozen=True)
class EngagementResult:
    score: float
    recent: float
    long_term: float
    permit_quota: float | None


def normalize_history(
    history: Sequence[object],
    *,
    recent_limit: int,
    long_term_limit: int,
) -> tuple[list[float], list[float]]:
    def _coerce_sequence(items: Iterable[object]) -> list[float]:
        values: list[float] = []
        limit = max(recent_limit, long_term_limit)
        for item in list(items)[:limit]:
            coerced = coerce_float(item)
            if coerced is not None:
                values.append(coerced)
        return values

    nested: list[Sequence[object]] = []
    for item in history:
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            nested.append(item)
    if nested:
        recent_source = nested[0]
        long_term_source = nested[1] if len(nested) > 1 else nested[0]
        recent_values = _coerce_sequence(recent_source)[:recent_limit]
        long_term_values = _coerce_sequence(long_term_source)[:long_term_limit]
        return recent_values, long_term_values

    values = _coerce_sequence(history)
    return values[:recent_limit], values[:long_term_limit]


def score_from_values(values: Sequence[float], *, target: float) -> float:
    if not values:
        return 0.0
    average = sum(values) / len(values)
    if target > 0:
        average = average / target
    return clamp_unit_interval(average)


def calculate_engagement(
    history: Sequence[object],
    *,
    history_limit: int,
    long_term_limit: int,
    target_reactions: float,
    long_term_weight: float,
    permit_quota_weight: float,
    permit_quota_ratio: float | None,
) -> EngagementResult:
    recent_values, long_term_values = normalize_history(
        history,
        recent_limit=history_limit,
        long_term_limit=long_term_limit,
    )

    recent_score = score_from_values(recent_values, target=target_reactions)
    long_term_source = long_term_values or recent_values
    long_term_score = score_from_values(long_term_source, target=target_reactions)

    score = recent_score
    if long_term_weight > 0.0:
        score = clamp_unit_interval(
            recent_score * (1.0 - long_term_weight)
            + long_term_score * long_term_weight
        )

    permit_quota = (
        clamp_unit_interval(permit_quota_ratio)
        if permit_quota_ratio is not None
        else None
    )
    if permit_quota is not None and permit_quota_weight > 0.0:
        score = clamp_unit_interval(
            score * (1.0 - permit_quota_weight)
            + permit_quota * permit_quota_weight
        )

    return EngagementResult(
        score=score,
        recent=recent_score,
        long_term=long_term_score,
        permit_quota=permit_quota,
    )


__all__ = [
    "EngagementResult",
    "calculate_engagement",
    "normalize_history",
    "score_from_values",
]
