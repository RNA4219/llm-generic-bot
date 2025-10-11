from __future__ import annotations

import re
from pathlib import Path


def _extract_job_block(yaml_text: str, job_name: str) -> str | None:
    pattern = rf"(?ms)^\s{{2}}{re.escape(job_name)}:\n(.*?)(?=^\s{{2}}\w|\Z)"
    match = re.search(pattern, yaml_text)
    return match.group(1) if match else None


def test_ci_workflow_has_expected_jobs():
    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists(), "ci workflow file is missing"

    yaml_text = workflow_path.read_text(encoding="utf-8")
    assert re.search(r"^jobs:\n", yaml_text, re.MULTILINE), "jobs section must be defined"

    for job_name, expected_command in (
        ("lint", "ruff"),
        ("type", "mypy"),
        ("test", "pytest"),
    ):
        job_block = _extract_job_block(yaml_text, job_name)
        assert job_block is not None, f"missing '{job_name}' job"
        run_pattern = rf"^\s{{6}}- run: .*{expected_command}"
        assert re.search(run_pattern, job_block, re.MULTILINE), (
            f"{job_name} job must run {expected_command}"
        )
