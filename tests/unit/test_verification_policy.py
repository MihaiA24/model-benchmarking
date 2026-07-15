from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify  # noqa: E402
from verification.policy import (  # noqa: E402
    Change,
    changes_from_file,
    changes_from_git,
    load_policy,
    tracked_paths,
)
POLICY = load_policy(ROOT / "verification/policy.json")


def test_policy_classifies_every_tracked_and_issue_owned_path() -> None:
    paths = set(tracked_paths(ROOT))
    paths.update(
        {
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
    )

    assert POLICY.audit_paths(paths) == ()


def test_typical_module_edit_selects_only_declared_docker_free_slice() -> None:
    selection = POLICY.select(
        [Change(status="M", path="src/model_benchmark/analysis/__init__.py")]
    )

    assert selection.development == ("architecture",)
    assert selection.cached_integration == ()
    assert selection.fresh_gates == ()
    assert selection.fallback is False


@pytest.mark.parametrize("status", ["A", "D", "R"])
def test_structural_changes_select_broad_development_and_every_gate(
    status: str,
) -> None:
    selection = POLICY.select(
        [
            Change(
                status=status,
                path="src/model_benchmark/analysis/new.py",
                previous_path=(
                    "src/model_benchmark/analysis/old.py" if status == "R" else None
                ),
            )
        ]
    )

    assert selection.development == (POLICY.broad_development_slice,)
    assert selection.fresh_gates == tuple(sorted(POLICY.fresh_gates))
    assert selection.fallback is True


def test_unclassified_path_fails_closed() -> None:
    selection = POLICY.select([Change(status="M", path="unknown/new-boundary.xyz")])

    assert selection.development == (POLICY.broad_development_slice,)
    assert selection.fresh_gates == tuple(sorted(POLICY.fresh_gates))
    assert selection.fallback is True


def test_issue_acceptance_edit_selects_only_the_complete_named_gate() -> None:
    selection = POLICY.select(
        [
            Change(
                status="M",
                path="tests/acceptance/issue_29/test_scenario_authoring.py",
            )
        ]
    )

    assert selection.fresh_gates == ("issue-29",)
    gate = POLICY.fresh_gates[selection.fresh_gates[0]]
    commands = gate["commands"]
    assert isinstance(commands, list)
    assert [command["command"] for command in commands] == [
        "uv run --frozen pytest -q tests/acceptance/issue_29 --maxfail=1"
    ]


def test_shared_policy_change_is_monotone_across_every_gate() -> None:
    selection = POLICY.select(
        [Change(status="M", path="verification/policy.json")]
    )

    assert selection.development == ("verification-policy",)
    assert selection.fresh_gates == tuple(sorted(POLICY.fresh_gates))


def test_explicit_non_normative_prose_selects_no_verification() -> None:
    selection = POLICY.select([Change(status="M", path="README.md")])

    assert selection.development == ()
    assert selection.cached_integration == ()
    assert selection.fresh_gates == ()
    assert selection.fallback is False


def test_changed_path_file_supports_plain_status_and_rename(tmp_path: Path) -> None:
    path = tmp_path / "changes.txt"
    path.write_text(
        "src/model_benchmark/cli.py\n"
        "D\ttests/unit/test_cli.py\n"
        "R100\told.py\tnew.py\n",
        encoding="utf-8",
    )

    assert changes_from_file(path) == (
        Change(status="M", path="src/model_benchmark/cli.py"),
        Change(status="D", path="tests/unit/test_cli.py"),
        Change(status="R", path="new.py", previous_path="old.py"),
    )


def test_git_derived_selection_preserves_add_modify_and_rename(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "verification@example.invalid")
    _git(repository, "config", "user.name", "Verification Test")
    (repository / "modified.txt").write_text("before\n", encoding="utf-8")
    (repository / "renamed.txt").write_text("stable content\n" * 20, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD").strip()

    (repository / "modified.txt").write_text("after\n", encoding="utf-8")
    (repository / "added.txt").write_text("new\n", encoding="utf-8")
    _git(repository, "mv", "renamed.txt", "moved.txt")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "change")
    head = _git(repository, "rev-parse", "HEAD").strip()

    changes = changes_from_git(repository, base, head)

    assert {(change.status, change.path, change.previous_path) for change in changes} == {
        ("A", "added.txt", None),
        ("M", "modified.txt", None),
        ("R", "moved.txt", "renamed.txt"),
    }


def test_development_command_rejects_authoritative_and_docker_shapes() -> None:
    with pytest.raises(verify.DevelopmentRunError):
        verify._development_argv(
            "uv run --offline --frozen pytest -q tests/acceptance/issue_54 --maxfail=1"
        )
    with pytest.raises(verify.DevelopmentRunError):
        verify._development_argv("uv run --offline --frozen docker info")


def test_development_network_attempt_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_uv(tmp_path, monkeypatch)
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    command = (
        "uv run --offline --frozen python -c "
        '"import socket; socket.create_connection((\'example.com\', 443))"'
    )
    policy, selection = _development_policy(command)

    with pytest.raises(verify.DevelopmentRunError):
        verify.run_development(policy, selection)


def test_development_publication_attempt_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_uv(tmp_path, monkeypatch)
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    existing = tmp_path / "artifacts/acceptance/issue-28/verification.json"
    existing.parent.mkdir(parents=True)
    existing.write_text("trusted\n", encoding="utf-8")
    command = (
        "uv run --offline --frozen python -c "
        '"from pathlib import Path; p=Path(\'artifacts/acceptance/issue-999/verification.json\'); '
        'p.parent.mkdir(parents=True); p.write_text(\'forged\')"'
    )
    policy, selection = _development_policy(command)

    with pytest.raises(verify.DevelopmentRunError):
        verify.run_development(policy, selection)

    assert existing.read_text(encoding="utf-8") == "trusted\n"
    assert not (tmp_path / "artifacts/acceptance/issue-999").exists()


def _development_policy(command: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    policy = SimpleNamespace(
        development_slices={
            "probe": {
                "authority": "none",
                "commands": [command],
                "id": "probe",
            }
        },
        sha256="0" * 64,
    )
    selection = SimpleNamespace(development=("probe",))
    return policy, selection


def _install_fake_uv(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary_root = root / "bin"
    binary_root.mkdir()
    uv = binary_root / "uv"
    uv.write_text("#!/bin/sh\nshift 3\nexec \"$@\"\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(binary_root), os.environ["PATH"]])
    )


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
