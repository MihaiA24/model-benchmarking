from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [Path(sys.executable).with_name("model-benchmark"), *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_cli_help_exposes_exact_functional_v1_commands() -> None:
    completed = _run("--help")

    assert completed.returncode == 0
    assert "usage: model-benchmark" in completed.stdout
    assert "--home" in completed.stdout
    assert "--json" in completed.stdout
    for command in ("provision", "preflight", "run", "inspect"):
        assert command in completed.stdout
    assert "scenario" not in completed.stdout
    assert completed.stderr == ""


def test_cli_requires_one_operator_command() -> None:
    completed = _run()

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("usage error:")


def test_cli_usage_failure_is_one_canonical_json_document() -> None:
    completed = _run("--json")

    assert completed.returncode == 2
    assert completed.stderr == ""
    summary = json.loads(completed.stdout)
    assert summary == {
        "command": "cli",
        "message": "the following arguments are required: command",
        "outcome": "rejected",
        "reason_code": "invalid-cli-usage",
    }
    assert completed.stdout == json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
