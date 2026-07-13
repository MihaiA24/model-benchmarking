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


def test_cli_help_is_concise_and_noninteractive() -> None:
    completed = _run("--help")

    assert completed.returncode == 0
    assert "usage: model-benchmark" in completed.stdout
    assert "--json" in completed.stdout
    assert completed.stderr == ""


def test_cli_emits_machine_readable_canonical_summary() -> None:
    completed = _run("--json")

    assert completed.returncode == 0
    assert completed.stderr == ""
    summary = json.loads(completed.stdout)
    assert summary == {
        "modules": ["analysis", "declarations", "evidence", "runtime"],
        "program": "model-benchmark",
        "status": "foundation-ready",
        "version": "0.1.0",
    }
    assert completed.stdout == json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def test_cli_human_summary_is_concise() -> None:
    completed = _run()

    assert completed.returncode == 0
    assert completed.stdout == "model-benchmark 0.1.0 — foundation ready\n"
    assert completed.stderr == ""
