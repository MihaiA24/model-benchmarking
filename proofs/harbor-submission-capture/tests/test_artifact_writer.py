from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import conftest as artifact_writer


PROOF_ROOT = Path(__file__).resolve().parents[1]


def test_collection_failure_removes_prior_authoritative_artifacts(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proof"
    tests_dir = project / "tests"
    cases_dir = project / "artifacts" / "cases"
    tests_dir.mkdir(parents=True)
    cases_dir.mkdir(parents=True)
    shutil.copy2(PROOF_ROOT / "tests/conftest.py", tests_dir / "conftest.py")
    (tests_dir / "test_broken.py").write_text("def broken(\n", encoding="utf-8")

    authoritative = [
        project / "artifacts/proof-report.json",
        project / "artifacts/sha256sums.txt",
        cases_dir / "stale.json",
    ]
    for path in authoritative:
        path.write_text("stale\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(tests_dir), "--maxfail=1"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert all(not path.exists() for path in authoritative)


def test_publication_exception_removes_partial_authoritative_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    case_root = artifact_root / "cases"
    monkeypatch.setattr(artifact_writer, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(artifact_writer, "CASE_ROOT", case_root)
    monkeypatch.setattr(artifact_writer, "_REQUESTED_FULL_PROOF_SUITE", True)
    monkeypatch.setattr(artifact_writer, "_FULL_PROOF_SUITE", True)
    monkeypatch.setattr(artifact_writer, "_ANY_SKIP", False)
    monkeypatch.setattr(
        artifact_writer,
        "_CASE_RESULTS",
        {
            case: {"nodeid": case, "outcome": "passed"}
            for case in artifact_writer.CASE_DISPOSITIONS
        },
    )

    partial = [
        artifact_root / "proof-report.json",
        artifact_root / "sha256sums.txt",
        case_root / "partial.json",
    ]

    def fail_during_publication() -> None:
        for path in partial:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("partial\n", encoding="utf-8")
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(
        artifact_writer,
        "_publish_authoritative_outputs",
        fail_during_publication,
    )

    class Session:
        exitstatus = pytest.ExitCode.OK

    session = Session()
    finish: Any = artifact_writer.pytest_sessionfinish
    with pytest.raises(RuntimeError, match="injected publication failure"):
        finish(session, pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert all(not path.exists() for path in partial)
