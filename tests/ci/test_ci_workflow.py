from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _collect_job_commands(yaml_text: str) -> dict[str, list[str]]:
    in_jobs = False
    current_job: str | None = None
    in_steps = False
    anchors: dict[str, list[str]] = {}
    job_commands: dict[str, list[str]] = {}
    current_anchor: str | None = None
    tracking_step = False

    for raw_line in yaml_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if not in_jobs:
            if stripped == "jobs:":
                in_jobs = True
            continue

        if indent == 0 and not stripped.startswith("-"):
            break

        if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            current_job = stripped[:-1]
            job_commands.setdefault(current_job, [])
            in_steps = False
            tracking_step = False
            current_anchor = None
            continue

        if current_job is None:
            continue

        if indent == 4 and stripped == "steps:":
            in_steps = True
            tracking_step = False
            current_anchor = None
            continue

        if not in_steps:
            continue

        if indent == 6 and stripped.startswith("- "):
            tracking_step = True
            current_anchor = None
            content = stripped[2:].strip()
            if content.startswith("*"):
                alias = content[1:]
                job_commands[current_job].extend(anchors.get(alias, []))
                tracking_step = False
                continue
            if content.startswith("&"):
                parts = content.split(maxsplit=1)
                current_anchor = parts[0][1:]
                anchors.setdefault(current_anchor, [])
                content = parts[1] if len(parts) > 1 else ""
            if content.startswith("run:"):
                command = content.split("run:", 1)[1].strip()
                if command:
                    job_commands[current_job].append(command)
                    if current_anchor is not None:
                        anchors[current_anchor] = [command]
                tracking_step = False
                current_anchor = None
            continue

        if tracking_step and indent > 6 and stripped.startswith("run:"):
            command = stripped.split("run:", 1)[1].strip()
            if command:
                job_commands[current_job].append(command)
                if current_anchor is not None:
                    anchors[current_anchor] = [command]
            tracking_step = False
            current_anchor = None

    return job_commands


def _iter_run_commands(commands: dict[str, list[str]], job_name: str) -> Iterable[str]:
    yield from commands.get(job_name, [])


def test_ci_workflow_has_expected_jobs():
    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists(), "ci workflow file is missing"

    commands_by_job = _collect_job_commands(workflow_path.read_text(encoding="utf-8"))

    expected_jobs = {
        "lint": "ruff check .",
        "type": "mypy src",
        "test": "pytest -q",
    }

    for job_name, expected_command in expected_jobs.items():
        commands = list(_iter_run_commands(commands_by_job, job_name))
        assert commands, f"job '{job_name}' must define at least one run command"
        assert any(expected_command in command for command in commands), (
            f"job '{job_name}' must run '{expected_command}'"
        )
