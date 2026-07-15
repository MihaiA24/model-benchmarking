from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify  # noqa: E402
from verification.policy import Change, load_policy, tracked_paths  # noqa: E402


POLICY = load_policy(ROOT / "verification/policy.json")


def test_closed_world_selection_covers_targeted_and_fail_closed_paths() -> None:
    expected_new_paths = {
        "scripts/verify.py",
        "tests/acceptance/issue_54/test_verification_policy.py",
        "tests/architecture/test_import_boundaries.py",
        "tests/unit/test_verification_policy.py",
        "verification/__init__.py",
        "verification/policy.json",
        "verification/policy.py",
    }
    assert POLICY.audit_paths(set(tracked_paths(ROOT)) | expected_new_paths) == ()

    targeted = POLICY.select(
        [Change(status="M", path="src/model_benchmark/analysis/__init__.py")]
    )
    assert targeted.development == ("architecture",)
    assert targeted.cached_integration == ()
    assert targeted.fallback is False

    for change in (
        Change(status="A", path="new.py"),
        Change(status="D", path="old.py"),
        Change(status="R", path="new.py", previous_path="old.py"),
        Change(status="M", path="unclassified/new.py"),
    ):
        selection = POLICY.select([change])
        assert selection.development == (POLICY.broad_development_slice,)
        assert selection.cached_integration == ()
        assert selection.fallback is True


def test_issue_and_shared_inputs_select_local_verification() -> None:
    issue = POLICY.select(
        [Change(status="M", path="tests/acceptance/issue_29/test_case.py")]
    )
    assert issue.development == ("scenarios",)
    assert issue.cached_integration == ("scenario-contracts",)

    shared = POLICY.select([Change(status="M", path="verification/policy.json")])
    assert shared.development == ("verification-policy",)
    assert shared.cached_integration == ()

    prose = POLICY.select([Change(status="M", path="README.md")])
    assert prose.development == ()
    assert prose.cached_integration == ()


def test_tier_outputs_have_disjoint_authority_and_diagnostic_shape() -> None:
    selection = POLICY.select(
        [Change(status="M", path="src/model_benchmark/evidence/verification.py")]
    )
    document = POLICY.selection_document(selection)

    assert document["authority"] == "non_authoritative"
    assert set(document) == {
        "authority",
        "cached_integration",
        "changes",
        "development",
        "diagnostics",
        "fallback",
        "policy_sha256",
        "reasons",
        "schema",
    }
    assert all(item["authority"] == "none" for item in document["development"])
    assert all(
        item["authority"] == "diagnostic"
        for item in document["cached_integration"]
    )
    assert document["diagnostics"] == {
        "changed_path_count": 1,
        "shape": "verification-selection-diagnostics-v1",
    }


def test_development_denies_network_and_restores_authoritative_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_uv(tmp_path, monkeypatch)
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    trusted = tmp_path / "artifacts/acceptance/issue-28/verification.json"
    trusted.parent.mkdir(parents=True)
    trusted.write_text("trusted\n", encoding="utf-8")

    success_policy, selection = _development_policy(
        'uv run --offline --frozen python -c "pass"'
    )
    successful = verify.run_development(success_policy, selection)
    diagnostics = successful["diagnostics"]
    assert set(diagnostics) == {
        "command_count",
        "elapsed_ms",
        "max_rss_bytes",
        "shape",
    }
    assert diagnostics["shape"] == "development-run-diagnostics-v1"
    assert diagnostics["command_count"] == 1
    assert diagnostics["max_rss_bytes"] >= 0

    network_policy, selection = _development_policy(
        "uv run --offline --frozen python -c "
        '"import socket; socket.create_connection((\'example.com\', 443))"'
    )
    with pytest.raises(verify.DevelopmentRunError):
        verify.run_development(network_policy, selection)

    publication_policy, selection = _development_policy(
        "uv run --offline --frozen python -c "
        '"from pathlib import Path; p=Path(\'artifacts/acceptance/issue-999/verification.json\'); '
        'p.parent.mkdir(parents=True); p.write_text(\'forged\')"'
    )
    with pytest.raises(verify.DevelopmentRunError):
        verify.run_development(publication_policy, selection)

    assert trusted.read_text(encoding="utf-8") == "trusted\n"
    assert not (tmp_path / "artifacts/acceptance/issue-999").exists()
    with pytest.raises(verify.DevelopmentRunError):
        verify._development_argv("uv run --offline --frozen docker info")


@pytest.mark.parametrize(
    "extra",
    [
        ["-k", "case"],
        ["-m", "not_missing"],
        ["--ignore", "tests/acceptance/issue_99/test_case.py"],
        ["--deselect", "tests/acceptance/issue_99/test_case.py::test_case"],
    ],
    ids=["keyword", "marker", "ignore", "deselect"],
)
def test_partial_acceptance_selection_cannot_publish(
    tmp_path: Path,
    extra: list[str],
) -> None:
    project = _nested_acceptance_project(tmp_path)

    completed = _run_nested_acceptance(project, *extra)

    assert completed.returncode != 0
    _assert_no_issue_99_artifact(project)


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n@pytest.mark.skip(reason='mandatory')\ndef test_case():\n    pass\n",
        "import pytest\n@pytest.mark.xfail(reason='mandatory')\ndef test_case():\n    assert False\n",
    ],
    ids=["skip", "xfail"],
)
def test_non_passing_mandatory_case_cannot_publish(
    tmp_path: Path,
    source: str,
) -> None:
    project = _nested_acceptance_project(tmp_path, source)

    completed = _run_nested_acceptance(project)

    assert completed.returncode != 0
    _assert_no_issue_99_artifact(project)


def test_missing_mandatory_inventory_cannot_publish(tmp_path: Path) -> None:
    project = _nested_acceptance_project(tmp_path, source=None)

    completed = _run_nested_acceptance(project)

    assert completed.returncode != 0
    _assert_no_issue_99_artifact(project)


def _development_policy(command: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    return (
        SimpleNamespace(
            development_slices={"probe": {"commands": [command]}},
            sha256="0" * 64,
        ),
        SimpleNamespace(development=("probe",)),
    )


def _install_fake_uv(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary_root = root / "bin"
    binary_root.mkdir()
    uv = binary_root / "uv"
    uv.write_text("#!/bin/sh\nshift 3\nexec \"$@\"\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(binary_root), os.environ["PATH"]]),
    )



def _nested_acceptance_project(
    tmp_path: Path,
    source: str | None = "def test_case():\n    assert True\n",
) -> Path:
    project = tmp_path / "nested"
    issue = project / "tests/acceptance/issue_99"
    issue.mkdir(parents=True)
    (project / "src").mkdir()
    (project / "src/foundation.txt").write_text("source\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "tests/conftest.py").write_text("", encoding="utf-8")
    if source is not None:
        (issue / "test_case.py").write_text(source, encoding="utf-8")
    return project


def _run_nested_acceptance(
    project: Path,
    *extra: str,
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
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _assert_no_issue_99_artifact(project: Path) -> None:
    assert not (project / "artifacts/acceptance/issue-99/verification.json").exists()
    assert not (project / "artifacts/acceptance/issue-99/sha256sums.txt").exists()
