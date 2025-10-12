from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from random import Random
from typing import Any, Mapping, Sequence, cast

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    yaml = None

yaml = cast("Any | None", yaml)

Template = tuple[str, str]


async def build_omikuji_post(
    cfg: Mapping[str, Any],
    *,
    user_id: str,
    today: date | None = None,
) -> str:
    omikuji_cfg = cfg.get("omikuji")
    if not isinstance(omikuji_cfg, Mapping):  # pragma: no cover - config misuse
        raise ValueError("missing omikuji configuration")

    templates = _collect_templates(omikuji_cfg)
    fortunes = _collect_fortunes(omikuji_cfg.get("fortunes"))
    active_day = today or date.today()
    template_id, text = templates[_select_template_index(omikuji_cfg, active_day, len(templates))]
    fortune = _select_fortune(fortunes, user_id=user_id, today=active_day)
    return text.format(fortune=fortune, user_id=user_id, template_id=template_id)


def _collect_templates(config: Mapping[str, Any]) -> Sequence[Template]:
    lookup = _locale_lookup(Path(config["locales_path"])) if "locales_path" in config else _locale_lookup()
    items: list[Template] = []
    for raw in config.get("templates", []):
        if isinstance(raw, Mapping):
            template_id = str(raw.get("id") or raw.get("name") or "template")
            text = raw.get("text") or lookup(raw.get("fallback_key", ""))
            if text:
                items.append((template_id, str(text)))
    if not items:
        raise ValueError("omikuji templates are required")
    return items


def _collect_fortunes(raw: Any) -> Sequence[str]:
    fortunes = [str(entry.get("value")) for entry in raw or [] if isinstance(entry, Mapping) and entry.get("value") is not None]
    fortunes.extend(str(entry) for entry in raw or [] if not isinstance(entry, Mapping))
    if not fortunes:
        raise ValueError("omikuji fortunes are required")
    return fortunes


def _select_template_index(config: Mapping[str, Any], active_day: date, template_count: int) -> int:
    anchor_raw = config.get("rotation_anchor")
    if isinstance(anchor_raw, date):
        anchor = anchor_raw
    elif isinstance(anchor_raw, str):
        anchor = date.fromisoformat(anchor_raw)
    else:
        anchor = active_day.replace(month=1, day=1)
    delta_days = (active_day - anchor).days
    return (delta_days + int(config.get("rotation_offset", 0))) % template_count


def _select_fortune(fortunes: Sequence[str], *, user_id: str, today: date) -> str:
    seed_bytes = f"{user_id}:{today.isoformat()}".encode("utf-8")
    rng = Random(int.from_bytes(sha256(seed_bytes).digest()[:8], "big"))
    return rng.choice(fortunes)


def _locale_lookup(path: Path | None = None):
    resolved = path or Path("config/locales/ja.yml")

    @lru_cache(maxsize=1)
    def _load() -> Mapping[str, str]:
        if not resolved.exists():
            return {}
        text = resolved.read_text(encoding="utf-8")
        data = _parse_locale(text)
        return _flatten_locale(data)

    def _lookup(key: str) -> str:
        if not key:
            return ""
        cache = _load()
        value = cache.get(key)
        if value is not None:
            return value
        prefixed = cache.get(f"ja.{key}")
        return prefixed if prefixed is not None else ""

    return _lookup


def _parse_locale(text: str) -> Mapping[str, Any]:
    if yaml is not None:
        loaded = yaml.safe_load(text)  # type: ignore[no-untyped-call]
        return loaded or {}
    parsed = json.loads(text)
    if isinstance(parsed, Mapping):
        return parsed
    return {}


def _flatten_locale(data: Mapping[str, Any]) -> Mapping[str, str]:
    flattened: dict[str, str] = {}
    stack: list[tuple[str, Any]] = [("", data)]
    while stack:
        prefix, value = stack.pop()
        if isinstance(value, Mapping):
            for key, inner in value.items():
                stack.append((f"{prefix}.{key}" if prefix else str(key), inner))
        else:
            flattened[prefix] = str(value)
    return flattened


__all__ = ["build_omikuji_post"]
