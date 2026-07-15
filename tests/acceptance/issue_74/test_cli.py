from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from model_benchmark.cli import main
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.runtime.functional_v1 import (
    CommandResult,
    FunctionalV1Home,
    FunctionalV1Runtime,
)


_RUN_ID = "019819f0-7400-7000-8000-000000000001"


class _FixtureRuntime:
    def __init__(self, home: FunctionalV1Home) -> None:
        self.home = home
        self.calls: list[tuple[str, str]] = []

    def _manifest_result(
        self,
        command: str,
        manifest: FunctionalV1Manifest,
    ) -> CommandResult:
        self.calls.append((command, str(manifest.identity)))
        return CommandResult(
            exit_code=0,
            human=f"{command} succeeded",
            payload={
                "command": command,
                "manifest_identity": str(manifest.identity),
                "outcome": "succeeded",
            },
        )

    def provision(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._manifest_result("provision", manifest)

    def preflight(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._manifest_result("preflight", manifest)

    def run(self, manifest: FunctionalV1Manifest) -> CommandResult:
        return self._manifest_result("run", manifest)

    def resume(self, run_id: str) -> CommandResult:
        self.calls.append(("resume", run_id))
        return CommandResult(
            exit_code=0,
            human="resume succeeded",
            payload={"command": "run", "outcome": "succeeded", "run_id": run_id},
        )

    def inspect(self, run_id: str) -> CommandResult:
        self.calls.append(("inspect", run_id))
        return CommandResult(
            exit_code=0,
            human="SCENARIO | CONDITION | DISPOSITION | TASK | ACCEPT | REGRESS | DURATION | REQUESTS | TOKENS | COST_USD | BUNDLE",
            payload={
                "command": "inspect",
                "outcome": "complete",
                "run_id": run_id,
                "scores": {
                    "acceptance_score": "1",
                    "regression_score": "1",
                    "task_success": "1",
                },
            },
        )


@pytest.fixture
def fixture_runtime() -> tuple[list[_FixtureRuntime], object]:
    runtimes: list[_FixtureRuntime] = []

    def factory(home: FunctionalV1Home) -> FunctionalV1Runtime:
        runtime = _FixtureRuntime(home)
        runtimes.append(runtime)
        return runtime

    return runtimes, factory


def _canonical(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


@pytest.mark.parametrize("command", ["provision", "preflight", "run"])
def test_manifest_commands_smoke_through_public_cli_with_fixture_runtime(
    command: str,
    manifest_bundle: tuple[Path, dict[str, object]],
    fixture_runtime: tuple[list[_FixtureRuntime], object],
    capfd: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    runtimes, factory = fixture_runtime

    exit_code = main(
        [
            "--home",
            str(tmp_path / "home"),
            "--json",
            command,
            str(manifest_bundle[0]),
        ],
        runtime_factory=factory,
    )

    output = capfd.readouterr()
    payload = json.loads(output.out)
    assert exit_code == 0
    assert output.err == ""
    assert output.out == _canonical(payload)
    assert payload["command"] == command
    assert payload["outcome"] == "succeeded"
    assert runtimes[-1].calls == [(command, payload["manifest_identity"])]


@pytest.mark.parametrize(
    ("arguments", "expected_call"),
    [
        (["run", "--resume", _RUN_ID], ("resume", _RUN_ID)),
        (["inspect", _RUN_ID], ("inspect", _RUN_ID)),
    ],
)
def test_run_resume_and_inspect_accept_only_managed_home_run_id(
    arguments: list[str],
    expected_call: tuple[str, str],
    fixture_runtime: tuple[list[_FixtureRuntime], object],
    capfd: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    runtimes, factory = fixture_runtime

    exit_code = main(
        ["--home", str(tmp_path / "home"), "--json", *arguments],
        runtime_factory=factory,
    )

    output = capfd.readouterr()
    payload = json.loads(output.out)
    assert exit_code == 0
    assert output.err == ""
    assert output.out == _canonical(payload)
    assert runtimes[-1].calls == [expected_call]


def test_resume_rejects_a_replacement_manifest_as_canonical_usage_failure(
    manifest_bundle: tuple[Path, dict[str, object]],
    fixture_runtime: tuple[list[_FixtureRuntime], object],
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtimes, factory = fixture_runtime

    exit_code = main(
        [
            "--json",
            "run",
            str(manifest_bundle[0]),
            "--resume",
            _RUN_ID,
        ],
        runtime_factory=factory,
    )

    output = capfd.readouterr()
    payload = json.loads(output.out)
    assert exit_code == 2
    assert output.err == ""
    assert output.out == _canonical(payload)
    assert payload["reason_code"] == "invalid-cli-usage"
    assert runtimes == []


@pytest.mark.parametrize("exit_code", [1, 3])
def test_cli_preserves_runtime_outcome_exit_codes(
    exit_code: int,
    manifest_bundle: tuple[Path, dict[str, object]],
    capfd: pytest.CaptureFixture[str],
) -> None:
    class RejectedRuntime(_FixtureRuntime):
        def preflight(self, manifest: FunctionalV1Manifest) -> CommandResult:
            return CommandResult(
                exit_code=exit_code,
                human="preflight rejected",
                payload={
                    "command": "preflight",
                    "outcome": "rejected",
                    "reason_code": "fixture-rejection",
                },
            )

    returned = main(
        ["--json", "preflight", str(manifest_bundle[0])],
        runtime_factory=RejectedRuntime,
    )

    output = capfd.readouterr()
    assert returned == exit_code
    assert output.err == ""
    assert output.out == _canonical(json.loads(output.out))


def test_human_inspect_exposes_the_fixed_common_score_columns(
    fixture_runtime: tuple[list[_FixtureRuntime], object],
    capfd: pytest.CaptureFixture[str],
) -> None:
    _, factory = fixture_runtime

    exit_code = main(["inspect", _RUN_ID], runtime_factory=factory)

    output = capfd.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert output.out == (
        "SCENARIO | CONDITION | DISPOSITION | TASK | ACCEPT | REGRESS | "
        "DURATION | REQUESTS | TOKENS | COST_USD | BUNDLE\n"
    )
