from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def _load_workflow() -> dict[str, object]:
    assert WORKFLOW_PATH.exists(), "ci workflow file is missing"
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw_text)
    assert isinstance(workflow, dict)
    return workflow


def _iter_job_steps(workflow: dict[str, object], job_name: str) -> list[dict[str, object]]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"workflow must define job '{job_name}'"
    steps = job.get("steps")
    assert isinstance(steps, list), f"job '{job_name}' must define steps"
    return [step for step in steps if isinstance(step, dict)]


def test_ci_workflow_runs_expected_commands() -> None:
    workflow = _load_workflow()

    expected_commands = {
        "lint": "ruff check .",
        "type": "mypy src",
        "test": "pytest -q",
    }

    for job_name, expected_command in expected_commands.items():
        steps = _iter_job_steps(workflow, job_name)
        run_commands = [step.get("run", "") for step in steps]
        assert any(
            isinstance(command, str) and expected_command in command
            for command in run_commands
        ), f"job '{job_name}' must run '{expected_command}'"


def test_ci_workflow_notifies_slack_on_failure() -> None:
    workflow = _load_workflow()
    slack_jobs = ["lint", "type", "test", "codeql"]

    for job_name in slack_jobs:
        steps = _iter_job_steps(workflow, job_name)
        slack_steps = [
            step
            for step in steps
            if step.get("uses") == "slackapi/slack-github-action@v1.26.0"
        ]
        assert slack_steps, f"job '{job_name}' must notify Slack on failure"
        slack_step = slack_steps[-1]
        assert (
            slack_step.get("if") == "failure()"
        ), f"job '{job_name}' Slack step must run only on failures"
        with_section = slack_step.get("with")
        assert isinstance(with_section, dict), "Slack step must define inputs"
        webhook = with_section.get("webhook-url")
        assert (
            isinstance(webhook, str) and "secrets.SLACK_CI_WEBHOOK_URL" in webhook
        ), "Slack step must reference the Slack webhook secret"
        payload = with_section.get("payload")
        assert (
            isinstance(payload, str) and job_name in payload
        ), "Slack payload must mention the job name"


def test_ci_workflow_has_weekly_pip_audit_job() -> None:
    workflow = _load_workflow()
    on_section = workflow.get("on")
    assert isinstance(on_section, dict), "workflow must define triggers"
    schedule = on_section.get("schedule")
    assert isinstance(schedule, list) and schedule, "workflow must define schedule"
    assert any(
        isinstance(entry, dict) and "cron" in entry for entry in schedule
    ), "workflow schedule must include cron expression"

    steps = _iter_job_steps(workflow, "pip-audit")
    run_commands = [step.get("run", "") for step in steps]
    assert any(
        isinstance(command, str) and "pip install pip-audit" in command
        for command in run_commands
    ), "pip-audit job must install pip-audit"
    assert any(
        isinstance(command, str) and command.strip().startswith("pip-audit")
        for command in run_commands
    ), "pip-audit job must execute pip-audit"
