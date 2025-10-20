from __future__ import annotations

from typing import Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from ..features.weather.post_builder import ReactionHistoryProvider
else:
    from ..features.weather import ReactionHistoryProvider

_DEFAULT_HISTORY: tuple[int, ...] = (8, 6, 7, 5, 3)


async def sample_reaction_history(
    *,
    job: str,
    limit: int,
    platform: Optional[str],
    channel: Optional[str],
) -> Sequence[int]:
    """Return a truncated slice of the default engagement history."""
    del job, platform, channel
    if limit <= 0:
        return ()
    return _DEFAULT_HISTORY[-limit:]


SAMPLE_REACTION_HISTORY: ReactionHistoryProvider = sample_reaction_history

__all__ = ["SAMPLE_REACTION_HISTORY"]
