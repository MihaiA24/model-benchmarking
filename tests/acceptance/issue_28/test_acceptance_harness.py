from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from model_benchmark.evidence.attestation import (
    LivePrerequisite,
    seal_live_attestation,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = ROOT / "schemas"


def _project(tmp_path: Path, source: str = "def test_case():\n    assert True\n") -> Path:
    project = tmp_path / "nested"
    issue = project / "tests/acceptance/issue_99"
    issue.mkdir(parents=True)
    (project / "src").mkdir()
    (project / "src/foundation.txt").write_text("source\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "tests/conftest.py").write_text("", encoding="utf-8")
    (issue / "test_case.py").write_text(source, encoding="utf-8")
    return project


def _run(
    project: Path,
    *extra: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/acceptance/issue_99",
            "--maxfail=1",
            *extra,
        ],
        cwd=project,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _seed_stale_artifacts(project: Path) -> tuple[Path, Path]:
    artifact_root = project / "artifacts/acceptance/issue-99"
    artifact_root.mkdir(parents=True)
    outputs = (
        artifact_root / "verification.json",
        artifact_root / "sha256sums.txt",
    )
    for output in outputs:
        output.write_text("stale-success\n", encoding="utf-8")
    return outputs


def test_exact_issue_path_reproduces_artifacts_and_non_exact_path_fails(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    first = _run(project)
    assert first.returncode == 0, first.stdout + first.stderr
    artifact_root = project / "artifacts/acceptance/issue-99"
    first_bytes = {
        name: (artifact_root / name).read_bytes()
        for name in ("verification.json", "sha256sums.txt")
    }
    second = _run(project)
    assert second.returncode == 0, second.stdout + second.stderr
    assert {
        name: (artifact_root / name).read_bytes()
        for name in ("verification.json", "sha256sums.txt")
    } == first_bytes

    conftest = project / "tests/conftest.py"
    conftest.write_text(
        conftest.read_text(encoding="utf-8") + "# changed harness activation\n",
        encoding="utf-8",
    )
    changed = _run(project)
    assert changed.returncode == 0, changed.stdout + changed.stderr
    assert (artifact_root / "verification.json").read_bytes() != first_bytes[
        "verification.json"
    ]

    broad = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/acceptance", "--maxfail=1"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert broad.returncode != 0


def test_mandatory_skip_and_expected_failure_exit_nonzero_without_artifacts(
    tmp_path: Path,
) -> None:
    sources = [
        "import pytest\n@pytest.mark.skip(reason='mandatory')\ndef test_case():\n    pass\n",
        "import pytest\n@pytest.mark.xfail(reason='mandatory')\ndef test_case():\n    assert False\n",
    ]
    for index, source in enumerate(sources):
        project = _project(tmp_path / str(index), source)
        completed = _run(project)
        assert completed.returncode != 0
        assert not (project / "artifacts/acceptance/issue-99/verification.json").exists()
        assert not (project / "artifacts/acceptance/issue-99/sha256sums.txt").exists()


def test_collection_failure_removes_stale_authoritative_outputs(tmp_path: Path) -> None:
    project = _project(tmp_path, "def broken(\n")
    outputs = _seed_stale_artifacts(project)

    completed = _run(project)

    assert completed.returncode != 0
    assert all(not output.exists() for output in outputs)


def test_run_live_requires_and_accepts_only_a_sealed_non_secret_attestation(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    stale_outputs = _seed_stale_artifacts(project)
    assert _run(project, "--run-live").returncode != 0
    assert all(not output.exists() for output in stale_outputs)

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


def test_missing_docker_fails_without_skip_or_stale_outputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    stale_outputs = _seed_stale_artifacts(project)

    completed = _run(project, "--require-docker", env={"PATH": ""})

    assert completed.returncode != 0
    assert "skipped" not in completed.stdout.lower()
    assert all(not output.exists() for output in stale_outputs)


def test_require_docker_accepts_a_responding_daemon_probe_and_never_skips(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    binary_root = tmp_path / "bin"
    binary_root.mkdir()
    docker = binary_root / "docker"
    docker.write_text("#!/bin/sh\nprintf '\"29.4.0\"\\n'\n", encoding="utf-8")
    docker.chmod(0o755)

    completed = _run(project, "--require-docker", env={"PATH": str(binary_root)})

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "skipped" not in completed.stdout.lower()
