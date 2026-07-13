from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "nested"
    issue = project / "tests/acceptance/issue_99"
    issue.mkdir(parents=True)
    (project / "src").mkdir()
    (project / "src/foundation.txt").write_text("source\n", encoding="utf-8")
    (project / "tests/fixtures").mkdir()
    (project / "tests/fixtures/shared.txt").write_text("fixture-v1\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "tests/conftest.py").write_text("", encoding="utf-8")
    (issue / "test_selected.py").write_text(
        "def test_selected():\n    assert True\n",
        encoding="utf-8",
    )
    (issue / "test_omitted.py").write_text(
        "def test_omitted():\n    assert True\n",
        encoding="utf-8",
    )
    return project


def _run(
    project: Path,
    *extra: str,
    maxfail: int = 1,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/acceptance/issue_99",
            f"--maxfail={maxfail}",
            *extra,
        ],
        cwd=project,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _artifact_root(project: Path) -> Path:
    return project / "artifacts/acceptance/issue-99"


def _assert_no_authoritative_outputs(project: Path) -> None:
    artifact_root = _artifact_root(project)
    assert not (artifact_root / "verification.json").exists()
    assert not (artifact_root / "sha256sums.txt").exists()


def _seed_stale_outputs(project: Path) -> None:
    artifact_root = _artifact_root(project)
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "verification.json").write_text("stale\n", encoding="utf-8")
    (artifact_root / "sha256sums.txt").write_text("stale\n", encoding="utf-8")


def _verification_document(project: Path) -> dict[str, Any]:
    return json.loads((_artifact_root(project) / "verification.json").read_text())


def test_selection_and_deselection_cannot_publish_partial_success(tmp_path: Path) -> None:
    keyword_project = _project(tmp_path / "keyword")
    keyword = _run(keyword_project, "-k", "selected")
    assert keyword.returncode != 0, keyword.stdout + keyword.stderr
    _assert_no_authoritative_outputs(keyword_project)

    ignored_project = _project(tmp_path / "ignored")
    ignored = _run(
        ignored_project,
        "--ignore=tests/acceptance/issue_99/test_omitted.py",
    )
    assert ignored.returncode != 0, ignored.stdout + ignored.stderr
    _assert_no_authoritative_outputs(ignored_project)

    hook_project = _project(tmp_path / "hook")
    (hook_project / "tests/acceptance/issue_99/conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    del items[1:]\n",
        encoding="utf-8",
    )
    hook = _run(hook_project)
    assert hook.returncode != 0, hook.stdout + hook.stderr
    _assert_no_authoritative_outputs(hook_project)


def test_early_configuration_failure_removes_stale_outputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _seed_stale_outputs(project)

    completed = _run(project, maxfail=2)

    assert completed.returncode != 0, completed.stdout + completed.stderr
    _assert_no_authoritative_outputs(project)


def test_rejected_test_node_target_removes_stale_outputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _seed_stale_outputs(project)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/acceptance/issue_99/test_selected.py::test_selected",
            "--maxfail=1",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode != 0, completed.stdout + completed.stderr
    _assert_no_authoritative_outputs(project)


def test_initial_conftest_failure_removes_stale_outputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _seed_stale_outputs(project)
    (project / "tests/conftest.py").write_text("def broken(\n", encoding="utf-8")

    completed = _run(project)

    assert completed.returncode != 0, completed.stdout + completed.stderr
    _assert_no_authoritative_outputs(project)


def test_shared_fixture_changes_are_sealed_into_source_identity(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = _run(project)
    assert first.returncode == 0, first.stdout + first.stderr
    first_document = _verification_document(project)
    first_inputs = {
        item["name"]: item["digest"]
        for item in first_document["input_identities"]
    }

    (project / "tests/fixtures/shared.txt").write_text(
        "fixture-v2\n",
        encoding="utf-8",
    )
    second = _run(project)
    assert second.returncode == 0, second.stdout + second.stderr
    second_document = _verification_document(project)
    second_inputs = {
        item["name"]: item["digest"]
        for item in second_document["input_identities"]
    }

    assert second_inputs["acceptance-source-tree"] != first_inputs[
        "acceptance-source-tree"
    ]


def test_explicit_inputs_are_path_safe_and_sealed(tmp_path: Path) -> None:
    project = _project(tmp_path / "accepted")
    shared = project / "shared-assets"
    shared.mkdir()
    fixture = shared / "value.txt"
    fixture.write_text("v1\n", encoding="utf-8")

    first = _run(project, "--acceptance-input=shared-assets")
    assert first.returncode == 0, first.stdout + first.stderr
    first_digest = {
        item["name"]: item["digest"]
        for item in _verification_document(project)["input_identities"]
    }["acceptance-source-tree"]
    fixture.write_text("v2\n", encoding="utf-8")
    second = _run(project, "--acceptance-input=shared-assets")
    assert second.returncode == 0, second.stdout + second.stderr
    second_digest = {
        item["name"]: item["digest"]
        for item in _verification_document(project)["input_identities"]
    }["acceptance-source-tree"]
    assert second_digest != first_digest

    unsafe_project = _project(tmp_path / "unsafe")
    _seed_stale_outputs(unsafe_project)
    unsafe = _run(unsafe_project, "--acceptance-input=../outside")
    assert unsafe.returncode != 0, unsafe.stdout + unsafe.stderr
    _assert_no_authoritative_outputs(unsafe_project)

    symlink_project = _project(tmp_path / "symlink")
    _seed_stale_outputs(symlink_project)
    linked_root = symlink_project / "shared-assets"
    linked_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (linked_root / "escape.txt").symlink_to(outside)
    escaped = _run(symlink_project, "--acceptance-input=shared-assets")
    assert escaped.returncode != 0, escaped.stdout + escaped.stderr
    _assert_no_authoritative_outputs(symlink_project)


def test_verification_records_the_observed_python_process_command(tmp_path: Path) -> None:
    project = _project(tmp_path)
    completed = _run(project)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    document = _verification_document(project)
    assert document["command"] == shlex.join(
        [
            "@python-env/bin/python",
            "-m",
            "pytest",
            "-q",
            "tests/acceptance/issue_99",
            "--maxfail=1",
        ]
    )
    input_names = {item["name"] for item in document["input_identities"]}
    assert "launcher-argv-0" in input_names
    assert "python-executable" in input_names


def test_import_alias_architecture_regressions_pass() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/architecture/test_import_boundaries.py",
            "--maxfail=1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_required_docker_daemon_is_observable() -> None:
    docker = shutil.which("docker")
    assert docker is not None
    completed = subprocess.run(
        [docker, "info", "--format", "{{json .ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()


def test_failed_docker_daemon_probe_removes_stale_outputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _seed_stale_outputs(project)
    binary_root = tmp_path / "bin"
    binary_root.mkdir()
    docker = binary_root / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)

    completed = _run(project, "--require-docker", env={"PATH": str(binary_root)})

    assert completed.returncode != 0, completed.stdout + completed.stderr
    _assert_no_authoritative_outputs(project)
