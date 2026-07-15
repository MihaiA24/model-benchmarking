from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify  # noqa: E402
from verification.policy import Change, load_policy, tracked_paths  # noqa: E402
from verification.proof import (  # noqa: E402
    ProofError,
    ProofPointer,
    consume_proof,
    encode_pointer,
    source_tree_sha256,
)


POLICY = load_policy(ROOT / "verification/policy.json")
SCHEMA = ROOT / "verification/proof-envelope-v1.schema.json"


def test_closed_world_selection_covers_targeted_and_fail_closed_paths() -> None:
    expected_new_paths = {
        "scripts/verify.py",
        "tests/acceptance/issue_54/test_verification_policy.py",
        "tests/unit/test_proof_consumer.py",
        "tests/unit/test_verification_policy.py",
        "verification/__init__.py",
        "verification/policy.json",
        "verification/policy.py",
        "verification/proof-envelope-v1.schema.json",
        "verification/proof.py",
        "verification/publisher.py",
        ".github/actions/fresh-proof/action.yml",
        "tests/unit/test_proof_publisher.py",
    }
    assert POLICY.audit_paths(set(tracked_paths(ROOT)) | expected_new_paths) == ()

    targeted = POLICY.select(
        [Change(status="M", path="src/model_benchmark/analysis/__init__.py")]
    )
    assert targeted.development == ("architecture",)
    assert targeted.cached_integration == ()
    assert targeted.fresh_gates == ()
    assert targeted.fallback is False

    for change in (
        Change(status="A", path="new.py"),
        Change(status="D", path="old.py"),
        Change(status="R", path="new.py", previous_path="old.py"),
        Change(status="M", path="unclassified/new.py"),
    ):
        selection = POLICY.select([change])
        assert selection.development == (POLICY.broad_development_slice,)
        assert selection.fresh_gates == tuple(sorted(POLICY.fresh_gates))
        assert selection.fallback is True


def test_issue_and_shared_inputs_select_complete_monotone_gates() -> None:
    issue = POLICY.select(
        [Change(status="M", path="tests/acceptance/issue_29/test_case.py")]
    )
    assert issue.fresh_gates == ("issue-29",)
    gate = POLICY.fresh_gates["issue-29"]
    commands = gate["commands"]
    assert isinstance(commands, list)
    assert [command["command"] for command in commands] == [
        "uv run --frozen pytest -q tests/acceptance/issue_29 --maxfail=1"
    ]

    shared = POLICY.select([Change(status="M", path="verification/policy.json")])
    assert shared.fresh_gates == tuple(sorted(POLICY.fresh_gates))
    assert POLICY.select([Change(status="M", path="README.md")]).fresh_gates == ()


def test_tier_outputs_have_disjoint_authority_and_diagnostic_shape() -> None:
    selection = POLICY.select(
        [Change(status="M", path="src/model_benchmark/evidence/verification.py")]
    )
    document = POLICY.selection_document(selection)

    assert document["authority"] == "non_authoritative"
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


def test_diagnostic_or_legacy_evidence_cannot_impersonate_outer_proof(
    tmp_path: Path,
) -> None:
    selection = POLICY.selection_document(
        POLICY.select([Change(status="M", path="README.md")])
    )
    diagnostic = tmp_path / "diagnostic.json"
    diagnostic.write_text(json.dumps(selection), encoding="utf-8")
    legacy = ROOT / "artifacts/acceptance/issue-28/verification.json"

    for path in (diagnostic, legacy):
        with pytest.raises(ProofError):
            consume_proof(
                policy=POLICY,
                project_root=ROOT,
                schema_path=SCHEMA,
                envelope_path=path,
                bundle_root=ROOT,
                api_get=lambda _repository, _path: {},
            )


def test_exact_live_current_proof_accepts_once_and_newer_attempt_revokes(
    tmp_path: Path,
) -> None:
    envelope, envelope_path, bundle_root = _proof(tmp_path)
    envelope_sha = _digest(envelope_path)
    api = _api(envelope, envelope_sha)

    accepted = consume_proof(
        policy=POLICY,
        project_root=ROOT,
        schema_path=SCHEMA,
        envelope_path=envelope_path,
        bundle_root=bundle_root,
        api_get=api,
    )
    assert accepted["accepted"] is True

    pending_api = _api(envelope, envelope_sha, newer_status="in_progress")
    with pytest.raises(ProofError, match="newest trusted Check Run"):
        consume_proof(
            policy=POLICY,
            project_root=ROOT,
            schema_path=SCHEMA,
            envelope_path=envelope_path,
            bundle_root=bundle_root,
            api_get=pending_api,
        )

    with pytest.raises(ProofError, match="unavailable"):
        consume_proof(
            policy=POLICY,
            project_root=ROOT,
            schema_path=SCHEMA,
            envelope_path=envelope_path,
            bundle_root=bundle_root,
            api_get=lambda _repository, _path: (_ for _ in ()).throw(
                ProofError("unavailable")
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    ["policy", "command", "cases", "worker", "checksum"],
)
def test_proof_identity_drift_fails_before_reuse(
    tmp_path: Path,
    mutation: str,
) -> None:
    envelope, envelope_path, bundle_root = _proof(tmp_path)
    if mutation == "policy":
        envelope["policy_sha256"] = "0" * 64
    elif mutation == "command":
        envelope["commands"][0]["command"] = "uv sync"
    elif mutation == "cases":
        envelope["commands"][1]["cases"] = envelope["commands"][1]["cases"][1:]
    elif mutation == "worker":
        envelope["worker"]["class"] = "unqualified"
    elif mutation == "checksum":
        envelope["child_artifacts"][0]["sha256"] = "0" * 64
    envelope_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    (bundle_root / "sha256sums.txt").write_text(
        f"{_digest(envelope_path)}  proof-envelope.json\n", encoding="utf-8"
    )

    with pytest.raises(ProofError):
        consume_proof(
            policy=POLICY,
            project_root=ROOT,
            schema_path=SCHEMA,
            envelope_path=envelope_path,
            bundle_root=bundle_root,
            api_get=_api(envelope, _digest(envelope_path)),
        )


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


def _proof(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    bundle_root = tmp_path / "bundle"
    child_root = bundle_root / "artifacts/acceptance/issue-28"
    child_root.mkdir(parents=True)
    source_root = ROOT / "artifacts/acceptance/issue-28"
    for name in ("verification.json", "sha256sums.txt"):
        shutil.copyfile(source_root / name, child_root / name)
    verification = json.loads((child_root / "verification.json").read_text())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    gate = POLICY.fresh_gates["issue-28"]
    envelope: dict[str, object] = {
        "authority": "fresh_authoritative",
        "candidate_sha": head,
        "child_artifacts": [
            {
                "path": f"artifacts/acceptance/issue-28/{name}",
                "sha256": _digest(child_root / name),
            }
            for name in ("verification.json", "sha256sums.txt")
        ],
        "commands": [
            {
                "cases": (
                    verification["case_results"]
                    if command["case_inventory"] == "required"
                    else []
                ),
                "command": command["command"],
                "completed_at": "2026-07-15T10:01:00Z",
                "exit_code": 0,
                "id": command["id"],
                "outcome": "passed",
                "started_at": "2026-07-15T10:00:00Z",
                "timeout_seconds": command["timeout_seconds"],
            }
            for command in gate["commands"]
        ],
        "created_at": "2026-07-15T10:02:00Z",
        "gate_id": "issue-28",
        "generation_id": "123e4567-e89b-12d3-a456-426614174000",
        "policy_sha256": POLICY.sha256,
        "repository": POLICY.repository,
        "schema_sha256": _digest(SCHEMA),
        "source_tree_sha256": source_tree_sha256(ROOT, head),
        "version": 1,
        "worker": {
            "class": "local-reference",
            "docker_daemon": None,
            "identity": "acceptance-worker",
            "qualification_state": "qualified",
        },
        "workflow": {
            "check_run_id": 99,
            "path": gate["workflow_path"],
            "reason": "fixed-head review",
            "requester": "acceptance-test",
            "run_attempt": 1,
            "run_id": 10,
        },
    }
    envelope_path = bundle_root / "proof-envelope.json"
    envelope_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    (bundle_root / "sha256sums.txt").write_text(
        f"{_digest(envelope_path)}  proof-envelope.json\n", encoding="utf-8"
    )
    return envelope, envelope_path, bundle_root


def _api(
    envelope: dict[str, object],
    envelope_sha: str,
    *,
    newer_status: str | None = None,
) -> Callable[[str, str], object]:
    gate = POLICY.fresh_gates["issue-28"]
    pointer = encode_pointer(
        ProofPointer(
            gate_id="issue-28",
            policy_sha256=POLICY.sha256,
            run_id=10,
            run_attempt=1,
            generation_id=str(envelope["generation_id"]),
            envelope_sha256=envelope_sha,
            artifact_id=20,
        )
    )
    checks: list[dict[str, object]] = [
        {
            "app": {"slug": gate["trusted_app_slug"]},
            "conclusion": "success",
            "external_id": pointer,
            "id": 99,
            "head_sha": envelope["candidate_sha"],
            "name": gate["check_name"],
            "status": "completed",
        }
    ]
    if newer_status is not None:
        checks.append(
            {
                "app": {"slug": gate["trusted_app_slug"]},
                "conclusion": None,
                "external_id": "malformed",
                "id": 100,
                "head_sha": envelope["candidate_sha"],
                "name": gate["check_name"],
                "status": newer_status,
            }
        )

    def get(repository: str, path: str) -> object:
        assert repository == POLICY.repository
        if "/check-runs?" in path:
            return {"check_runs": checks}
        if path == "/actions/runs/10":
            return {
                "id": 10,
                "conclusion": "success",
                "head_sha": envelope["candidate_sha"],
                "path": gate["workflow_path"],
                "run_attempt": 1,
                "status": "completed",
            }
        if path == "/actions/artifacts/20":
            return {
                "id": 20,
                "name": (
                    f"fresh-proof-issue-28-"
                    f"{str(envelope['candidate_sha'])[:12]}-{envelope['generation_id']}"
                ),
                "expired": False,
                "workflow_run": {
                    "head_sha": envelope["candidate_sha"],
                    "id": 10,
                },
            }
        raise AssertionError(path)

    return get


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
