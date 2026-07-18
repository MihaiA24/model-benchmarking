from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_benchmark.declarations.identities import (  # noqa: E402
    DigestKind,
    TypedDigest,
)
from model_benchmark.evidence.pytest_acceptance import (  # noqa: E402
    _AcceptanceState,
    _verification_inputs,
)
from model_benchmark.evidence.verification import (  # noqa: E402
    VerificationCase,
    VerificationInput,
    write_verification_artifacts,
)
from verification.freshness import (  # noqa: E402
    FreshnessError,
    check_acceptance_proofs,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src/model_benchmark").mkdir(parents=True)
    (root / "src/model_benchmark/module.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    for directory in ("issue_7_sample", "issue_9_other"):
        suite = root / "tests/acceptance" / directory
        suite.mkdir(parents=True)
        (suite / "test_case.py").write_text(
            "def test_case():\n    assert True\n", encoding="utf-8"
        )
    (root / "tests/conftest.py").write_text("", encoding="utf-8")
    (root / "uv.lock").write_text("locked\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\n', encoding="utf-8"
    )
    return root


def _seal(
    root: Path,
    issue: int,
    directory: str,
    *,
    input_paths: tuple[str, ...] = (),
    extra_inputs: tuple[VerificationInput, ...] = (),
) -> None:
    state = _AcceptanceState(
        project_root=root,
        issue_path=root / "tests/acceptance" / directory,
        issue=issue,
    )
    for relative in input_paths:
        state.input_paths.append((root / relative).resolve())
    write_verification_artifacts(
        project_root=root,
        schema_root=SCHEMA_ROOT,
        issue=issue,
        command="pytest",
        inputs=_verification_inputs(state) + list(extra_inputs),
        cases=[VerificationCase(id="test_case.py::test_case", outcome="passed")],
    )


def _seal_all(root: Path) -> None:
    _seal(root, 7, "issue_7_sample")
    _seal(root, 9, "issue_9_other")


def _by_issue(reports: list[object]) -> dict[int, object]:
    return {report.issue: report for report in reports}


def test_fresh_tree_reports_every_proof_fresh(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _seal_all(root)

    reports = _by_issue(check_acceptance_proofs(root))

    assert {report.status for report in reports.values()} == {"fresh"}
    assert all(report.fresh for report in reports.values())


def test_source_tree_edit_fails_every_proof_closed(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _seal_all(root)
    (root / "src/model_benchmark/module.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )

    reports = _by_issue(check_acceptance_proofs(root))

    assert {report.status for report in reports.values()} == {"stale"}
    assert all(
        report.stale_inputs == ("acceptance-source-tree",)
        for report in reports.values()
    )


def test_suite_directory_edit_fails_only_that_proof(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _seal_all(root)
    (root / "tests/acceptance/issue_7_sample/test_case.py").write_text(
        "def test_case():\n    assert 1 == 1\n", encoding="utf-8"
    )

    reports = _by_issue(check_acceptance_proofs(root))

    assert reports[7].status == "stale"
    assert reports[9].status == "fresh"


def test_missing_artifacts_fail_closed(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _seal_all(root)
    (root / "artifacts/acceptance/issue-7/verification.json").unlink()

    reports = _by_issue(check_acceptance_proofs(root))

    assert reports[7].status == "missing"
    assert reports[9].status == "fresh"


def test_tampered_verification_document_fails_closed(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _seal_all(root)
    verification = root / "artifacts/acceptance/issue-7/verification.json"
    verification.write_bytes(verification.read_bytes() + b"\n")

    reports = _by_issue(check_acceptance_proofs(root))

    assert reports[7].status == "tampered"
    assert "checksum mismatch" in reports[7].detail


def test_declared_acceptance_inputs_participate_in_recomputation(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    (root / "extra").mkdir()
    (root / "extra/data.py").write_text("EXTRA = 1\n", encoding="utf-8")
    _seal(root, 7, "issue_7_sample", input_paths=("extra",))
    _seal(root, 9, "issue_9_other")

    with_extras = _by_issue(check_acceptance_proofs(root, {7: ("extra",)}))
    without_extras = _by_issue(check_acceptance_proofs(root))

    assert with_extras[7].status == "fresh"
    assert without_extras[7].status == "stale"
    assert without_extras[7].stale_inputs == ("acceptance-source-tree",)


def test_runtime_only_inputs_are_reported_not_recomputed(tmp_path: Path) -> None:
    root = _project(tmp_path)
    extra = VerificationInput(
        name="launcher-argv-0",
        digest=TypedDigest.from_bytes(DigestKind.ARTIFACT, b"launcher"),
    )
    _seal(root, 7, "issue_7_sample", extra_inputs=(extra,))
    _seal(root, 9, "issue_9_other")

    reports = _by_issue(check_acceptance_proofs(root))

    assert reports[7].status == "fresh"
    assert "launcher-argv-0" in reports[7].not_recomputable


def test_duplicate_issue_directories_are_rejected(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "tests/acceptance/issue_7_duplicate").mkdir()

    with pytest.raises(FreshnessError, match="issue 7 is claimed by both"):
        check_acceptance_proofs(root)
