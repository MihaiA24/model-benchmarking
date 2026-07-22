from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import acceptance  # noqa: E402


def test_stage_manifest_matches_directories_on_disk() -> None:
    acceptance.validate_layout(ROOT / "tests/acceptance", acceptance.STAGES)


def test_layout_drift_fails_in_both_directions(tmp_path: Path) -> None:
    for stage in acceptance.STAGES:
        (tmp_path / stage.directory).mkdir()

    (tmp_path / "issue_999_unregistered").mkdir()
    with pytest.raises(acceptance.SuiteLayoutError, match="issue_999_unregistered"):
        acceptance.validate_layout(tmp_path, acceptance.STAGES)

    (tmp_path / "issue_999_unregistered").rmdir()
    (tmp_path / acceptance.STAGES[0].directory).rmdir()
    with pytest.raises(acceptance.SuiteLayoutError, match=acceptance.STAGES[0].directory):
        acceptance.validate_layout(tmp_path, acceptance.STAGES)


def test_selection_accepts_number_slug_and_directory_tokens() -> None:
    by_number = acceptance.select_stages(acceptance.STAGES, "33", None)
    by_slug = acceptance.select_stages(acceptance.STAGES, "omp_condition", None)
    by_directory = acceptance.select_stages(
        acceptance.STAGES, "issue_33_omp_condition", None
    )
    assert by_number == by_slug == by_directory
    assert [stage.issue for stage in by_number] == [33]

    subset = acceptance.select_stages(acceptance.STAGES, "35,33,34", None)
    assert [stage.issue for stage in subset] == [33, 34, 35]

    tail = acceptance.select_stages(acceptance.STAGES, None, "51")
    assert [stage.issue for stage in tail] == [51, 54, 55, 74, 118, 123, 120]

    with pytest.raises(acceptance.SuiteLayoutError, match="unknown --only stage"):
        acceptance.select_stages(acceptance.STAGES, "no-such-stage", None)
    with pytest.raises(acceptance.SuiteLayoutError, match="unknown --from stage"):
        acceptance.select_stages(acceptance.STAGES, None, "no-such-stage")


def test_pytest_command_targets_exactly_one_issue_directory() -> None:
    stage = next(stage for stage in acceptance.STAGES if stage.issue == 51)
    command = acceptance.pytest_command(stage)
    assert command == [
        str(Path(sys.executable).with_name("pytest")),
        "-q",
        "tests/acceptance/issue_51_proof_hardening",
        "--maxfail=1",
        "-p",
        "no:cacheprovider",
        "--require-docker",
        "--acceptance-input=tests/architecture",
    ]


def test_missing_docker_daemon_is_reported_with_owning_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acceptance.shutil, "which", lambda _: None)
    docker_stages = tuple(stage for stage in acceptance.STAGES if stage.docker)
    with pytest.raises(acceptance.SuiteLayoutError, match="29, 51, 55"):
        acceptance.assert_docker_available(docker_stages)
    acceptance.assert_docker_available(
        tuple(stage for stage in acceptance.STAGES if not stage.docker)
    )


def test_readme_documents_every_stage() -> None:
    readme = (ROOT / "tests/acceptance/README.md").read_text(encoding="utf-8")
    for stage in acceptance.STAGES:
        assert stage.directory in readme, stage.directory
