from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - fallback for restricted environments
    from typing import Any, List, Sequence, Tuple

    def _strip_comment(line: str) -> str:
        in_single = False
        in_double = False
        for index, char in enumerate(line):
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "#" and not in_single and not in_double:
                return line[:index]
        return line

    def _tokenize(text: str) -> List[Tuple[int, str]]:
        tokens: List[Tuple[int, str]] = []
        for raw_line in text.splitlines():
            without_comment = _strip_comment(raw_line.rstrip())
            if not without_comment.strip():
                continue
            indent = len(without_comment) - len(without_comment.lstrip(" "))
            tokens.append((indent, without_comment.strip()))
        return tokens

    def _parse_scalar(value: str) -> Any:
        stripped = value.strip()
        if stripped == "{}":
            return {}
        if stripped == "[]":
            return []
        if stripped.startswith('"') and stripped.endswith('"'):
            return stripped[1:-1]
        if stripped.startswith("'") and stripped.endswith("'"):
            return stripped[1:-1]
        if stripped in {"true", "True"}:
            return True
        if stripped in {"false", "False"}:
            return False
        return stripped

    def _split_key_value(content: str) -> Tuple[str, str, bool]:
        if ": " in content:
            key, value = content.split(": ", 1)
            return key.strip(), value, True
        if content.endswith(":"):
            return content[:-1].strip(), "", False
        return content.strip(), "", False

    def _parse_block(tokens: Sequence[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
        result: Any = None
        position = index
        while position < len(tokens):
            current_indent, content = tokens[position]
            if current_indent < indent:
                break
            if current_indent > indent:
                child, position = _parse_block(tokens, position, current_indent)
                if result is None:
                    result = child
                elif isinstance(result, list):
                    result.append(child)
                else:
                    raise ValueError("Unexpected indentation")
                continue
            if content.startswith("- "):
                if result is None:
                    result = []
                elif not isinstance(result, list):
                    break
                item_content = content[2:].strip()
                position += 1
                if not item_content:
                    child, position = _parse_block(tokens, position, indent + 2)
                    result.append(child)
                    continue
                key, value_text, has_value = _split_key_value(item_content)
                if not has_value and not item_content.endswith(":" ):
                    result.append(_parse_scalar(item_content))
                    continue
                if not has_value:
                    child, position = _parse_block(tokens, position, indent + 2)
                    result.append({key: child})
                    continue
                scalar = _parse_scalar(value_text)
                if position < len(tokens) and tokens[position][0] >= indent + 2:
                    child, position = _parse_block(tokens, position, indent + 2)
                    if isinstance(child, dict):
                        merged = {key: scalar}
                        merged.update(child)
                        result.append(merged)
                        continue
                    if child is not None:
                        result.append({key: child})
                        continue
                result.append({key: scalar})
                continue
            key, value_text, has_value = _split_key_value(content)
            position += 1
            if has_value:
                scalar = _parse_scalar(value_text)
                if position < len(tokens) and tokens[position][0] >= indent + 2:
                    child, new_position = _parse_block(tokens, position, indent + 2)
                    if child is not None:
                        scalar = child
                        position = new_position
                if result is None:
                    result = {}
                result[key] = scalar
            else:
                child, position = _parse_block(tokens, position, indent + 2)
                if result is None:
                    result = {}
                result[key] = child
        return result, position

    class _MiniYAML:
        @staticmethod
        def safe_load(text: str) -> Any:
            tokens = _tokenize(text)
            if not tokens:
                return {}
            parsed, _ = _parse_block(tokens, 0, 0)
            return parsed

    yaml = _MiniYAML()


WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def _load_workflow() -> dict:
    with WORKFLOW_PATH.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp.read())


def test_slack_notification_step_exists() -> None:
    workflow = _load_workflow()
    jobs = workflow.get("jobs", {})

    slack_step_present = False
    for job in jobs.values():
        for step in job.get("steps", []):
            if "if" not in step or "failure()" not in str(step["if"]):
                continue
            env = step.get("env", {})
            values = list(env.values())
            run_value = step.get("run", "")
            has_secret = any("secrets.SLACK_WEBHOOK_URL" in str(value) for value in values)
            has_secret = has_secret or "secrets.SLACK_WEBHOOK_URL" in str(run_value)
            if has_secret:
                slack_step_present = True
                break
        if slack_step_present:
            break

    assert slack_step_present, "Slack notification step with failure() and webhook secret is required"


def test_security_job_runs_weekly_with_pip_audit() -> None:
    workflow = _load_workflow()

    schedule = workflow.get("on", {}).get("schedule", [])
    assert schedule, "A weekly schedule trigger must be configured"
    cron_expressions = [entry.get("cron", "") for entry in schedule]
    assert any(expression for expression in cron_expressions), "Schedule trigger must define at least one cron expression"

    jobs = workflow.get("jobs", {})
    security_job = jobs.get("security")
    assert security_job is not None, "Security job must be defined"

    steps = security_job.get("steps", [])
    assert any("pip-audit" in str(step.get("run", "")) for step in steps), "Security job must run pip-audit"
