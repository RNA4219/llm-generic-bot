from __future__ import annotations


def _strip(line: str) -> str:
    buf: list[str] = []; quote = ""
    for ch in line:
        if ch in {'"', "'"}:
            quote = "" if quote == ch else ch if not quote else quote
        if ch == "#" and not quote:
            break
        buf.append(ch)
    return "".join(buf).rstrip()


def _collect(text: str) -> list[tuple[int, str, str | None]]:
    items: list[tuple[int, str, str | None]] = []
    lines = text.splitlines(); i = 0
    while i < len(lines):
        raw = lines[i]; stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            i += 1; continue
        indent = len(raw) - len(stripped); content = _strip(stripped)
        if content.endswith(": >-"):
            key = content[:-3].rstrip(); block_lines: list[str] = []; i += 1; block_indent = None
            while i < len(lines):
                blk = lines[i]; blk_stripped = blk.lstrip(); blk_indent = len(blk) - len(blk_stripped)
                if blk_stripped and blk_indent <= indent:
                    break
                if not blk_stripped:
                    block_lines.append(""); i += 1; continue
                if block_indent is None:
                    block_indent = blk_indent
                block_lines.append(blk[block_indent:].rstrip()); i += 1
            items.append((indent, f"{key}:", "\n".join(block_lines))); continue
        items.append((indent, content, None)); i += 1
    return items


def _split(text: str, sep: str) -> list[str]:
    parts: list[str] = []; buf: list[str] = []; brace = bracket = 0; quote = ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch; buf.append(ch); continue
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket -= 1
        if ch == sep and brace == bracket == 0:
            parts.append("".join(buf).strip()); buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _value(token: str, block: str | None = None) -> object:
    if block is not None:
        return block
    token = token.strip()
    if not token:
        return None
    if token in {"true", "false"}:
        return token == "true"
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        return [_value(part) for part in _split(inner, ",") if part]
    if token.startswith("{") and token.endswith("}"):
        result: dict[str, object] = {}
        for part in _split(token[1:-1], ","):
            if not part:
                continue
            key, value = part.split(":", 1)
            result[key.strip()] = _value(value.strip())
        return result
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    return token


def _parse(items: list[tuple[int, str, str | None]], index: int, indent: int) -> tuple[object, int]:
    container: object | None = None
    while index < len(items):
        line_indent, content, block = items[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError("invalid indentation in workflow YAML")
        if content.startswith("- "):
            if container is None:
                container = []
            if not isinstance(container, list):
                raise ValueError("mixed collection types in YAML")
            remainder = content[2:].strip(); index += 1
            if not remainder:
                child, index = _parse(items, index, line_indent + 2); container.append(child); continue
            if ":" in remainder:
                key, value_token = remainder.split(":", 1)
                element: dict[str, object] = {key.strip(): _value(value_token.strip(), block)}
                child, index = _parse(items, index, line_indent + 2)
                if isinstance(child, dict) and child:
                    element.update(child)
                container.append(element)
            else:
                container.append(_value(remainder, block))
            continue
        if container is None:
            container = {}
        if not isinstance(container, dict):
            raise ValueError("mixed collection types in YAML")
        key, value_token = content.split(":", 1)
        key = key.strip(); value_text = value_token.strip(); index += 1
        if not value_text:
            child, index = _parse(items, index, line_indent + 2); container[key] = child
        else:
            container[key] = _value(value_text, block)
    return ({} if container is None else container, index)


class yaml:  # type: ignore[misc]
    @staticmethod
    def safe_load(text: str) -> object:
        items = _collect(text)
        data, pos = _parse(items, 0, 0)
        if pos != len(items):
            raise ValueError("failed to parse entire YAML document")
        return data

