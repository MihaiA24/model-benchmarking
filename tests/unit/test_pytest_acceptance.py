from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_benchmark.evidence.attestation import (
    LivePrerequisite,
    seal_live_attestation,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas"


def _project(
    tmp_path: Path,
    test_source: str = "def test_case():\n    assert True\n",
    directory: str = "issue_99",
) -> Path:
    project = tmp_path / "nested"
    issue = project / "tests/acceptance" / directory
    issue.mkdir(parents=True)
    (project / "src").mkdir()
    (project / "src/foundation.txt").write_text("source\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "tests/conftest.py").write_text("", encoding="utf-8")
    (issue / "test_case.py").write_text(test_source, encoding="utf-8")
    (project / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Acceptance Test",
            "-c",
            "user.email=acceptance@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=project,
        check=True,
    )
    return project


def _run(
    project: Path,
    *extra: str,
    env: dict[str, str] | None = None,
    directory: str = "issue_99",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"tests/acceptance/{directory}",
        "--maxfail=1",
        *extra,
    ]
    return subprocess.run(
        command,
        cwd=project,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_exact_issue_path_writes_reproducible_verified_artifacts(tmp_path: Path) -> None:
    project = _project(tmp_path)

    first = _run(project)
    assert first.returncode == 0, first.stdout + first.stderr
    artifact_root = project / "artifacts/acceptance/issue-99"
    first_bytes = {
        path.name: path.read_bytes()
        for path in [artifact_root / "verification.json", artifact_root / "sha256sums.txt"]
    }

    second = _run(project)
    assert second.returncode == 0, second.stdout + second.stderr
    assert {
        path.name: path.read_bytes()
        for path in [artifact_root / "verification.json", artifact_root / "sha256sums.txt"]
    } == first_bytes


def test_dirty_source_tree_refuses_publication(tmp_path: Path) -> None:
    project = _project(tmp_path)
    artifact_root = project / "artifacts/acceptance/issue-99"
    assert _run(project).returncode == 0
    (project / "src/untracked.py").write_text("pollution\n", encoding="utf-8")

    completed = _run(project)

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "acceptance source tree is dirty" in output
    assert "src/untracked.py" in output
    assert not (artifact_root / "verification.json").exists()
    assert not (artifact_root / "sha256sums.txt").exists()


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n@pytest.mark.skip(reason='mandatory')\ndef test_case():\n    pass\n",
        "import pytest\n@pytest.mark.xfail(reason='mandatory')\ndef test_case():\n    assert False\n",
    ],
    ids=["skip", "expected-failure"],
)
def test_mandatory_skip_and_expected_failure_are_rejected(
    tmp_path: Path,
    source: str,
) -> None:
    project = _project(tmp_path, source)

    completed = _run(project)

    assert completed.returncode != 0
    assert not (project / "artifacts/acceptance/issue-99/verification.json").exists()
    assert not (project / "artifacts/acceptance/issue-99/sha256sums.txt").exists()


def test_run_live_requires_a_valid_sealed_attestation(tmp_path: Path) -> None:
    project = _project(tmp_path)

    missing = _run(project, "--run-live")
    assert missing.returncode != 0

    attestation = project / "live-attestation.json"
    attestation.write_bytes(
        seal_live_attestation(
            schema_root=SCHEMA_ROOT,
            issue=99,
            prerequisites=[
                LivePrerequisite(name="access", evidence_ref="attestations/access.json")
            ],
        )
    )
    accepted = _run(
        project,
        "--run-live",
        env={"MODEL_BENCHMARK_LIVE_ATTESTATION": str(attestation)},
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_require_docker_accepts_a_responding_daemon_probe(tmp_path: Path) -> None:
    project = _project(tmp_path)
    binary_root = tmp_path / "bin"
    binary_root.mkdir()
    docker = binary_root / "docker"
    docker.write_text("#!/bin/sh\nprintf '\"29.4.0\"\\n'\n", encoding="utf-8")
    docker.chmod(0o755)

    completed = _run(
        project,
        "--require-docker",
        env={"PATH": f"{binary_root}{os.pathsep}{os.environ['PATH']}"},
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_non_exact_acceptance_path_is_rejected(tmp_path: Path) -> None:
    project = _project(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/acceptance", "--maxfail=1"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode != 0


def test_slugged_issue_directory_publishes_numeric_artifacts(tmp_path: Path) -> None:
    project = _project(tmp_path, directory="issue_99_sample_suite")

    completed = _run(project, directory="issue_99_sample_suite")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    artifact_root = project / "artifacts/acceptance/issue-99"
    assert (artifact_root / "verification.json").is_file()
    assert (artifact_root / "sha256sums.txt").is_file()


def test_duplicate_issue_directories_are_rejected(tmp_path: Path) -> None:
    project = _project(tmp_path, directory="issue_99_sample_suite")
    twin = project / "tests/acceptance/issue_99"
    twin.mkdir()
    (twin / "test_case.py").write_text("def test_case():\n    assert True\n", encoding="utf-8")

    completed = _run(project, directory="issue_99_sample_suite")

    assert completed.returncode != 0
    assert "multiple acceptance directories" in completed.stdout + completed.stderr
    assert not (project / "artifacts/acceptance/issue-99/verification.json").exists()
