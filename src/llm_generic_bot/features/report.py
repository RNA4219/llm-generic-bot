from __future__ import annotations

from typing import Any, Mapping


def build_weekly_report(
    snapshot: Mapping[str, Any] | object,
    *,
    fallback_body: str,
) -> dict[str, object]:
    return {"body": fallback_body, "tags": {}}
