"""Ordered runner for the authoritative Acceptance Verification Artifact suite.

Each stage produces one Acceptance Verification Artifact: a single
directory executed as its own pytest session so the acceptance plugin
(``model_benchmark.evidence.pytest_acceptance``) can publish
``artifacts/acceptance/issue-N/{verification.json,sha256sums.txt}``.

Stages run in dependency order; the manifest below is validated against the
directories on disk so the two can never drift silently.

Usage:
    uv run python scripts/acceptance.py --list
    uv run python scripts/acceptance.py                # full ordered suite
    uv run python scripts/acceptance.py --only 33,34,35
    uv run python scripts/acceptance.py --from 36 --keep-going
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ROOT = PROJECT_ROOT / "tests/acceptance"


class SuiteLayoutError(RuntimeError):
    """The stage manifest and tests/acceptance disagree."""


@dataclass(frozen=True)
class Stage:
    issue: int
    slug: str
    group: str
    proves: str
    docker: bool = False
    extra: tuple[str, ...] = ()

    @property
    def directory(self) -> str:
        return f"issue_{self.issue}_{self.slug}"

    @property
    def path(self) -> str:
        return f"tests/acceptance/{self.directory}"


STAGES: tuple[Stage, ...] = (
    Stage(
        issue=28,
        slug="foundation_harness",
        group="foundation",
        proves="Canonical JSON, identities, strict schemas, operator CLI, and the Acceptance Verification Artifact harness itself",
    ),
    Stage(
        issue=29,
        slug="scenario_authoring",
        group="authoring",
        proves="Scenario authoring lifecycle: scaffold, check/lock gates, and the Docker qualification pipeline",
        docker=True,
    ),
    Stage(
        issue=32,
        slug="condition_runner",
        group="conditions",
        proves="Credential proxy, raw-API materializer, and the generic sealed condition runner",
    ),
    Stage(
        issue=33,
        slug="omp_condition",
        group="conditions",
        proves="OMP v16.4.0 condition lock: sealed stock profile, digest-first provisioning, fresh RPC trials",
    ),
    Stage(
        issue=34,
        slug="opencode_condition",
        group="conditions",
        proves="OpenCode v1.17.18 condition lock: archive provisioning and stock stdin-JSON-events trials",
    ),
    Stage(
        issue=35,
        slug="hermes_condition",
        group="conditions",
        proves="Hermes v0.18.2 condition lock: image provisioning and native oneshot trials",
    ),
    Stage(
        issue=36,
        slug="execution_scheduler",
        group="runtime",
        proves="Sliding-window cell scheduler and Harbor executor terminal facts",
    ),
    Stage(
        issue=37,
        slug="evidence_sealing",
        group="runtime",
        proves="Drain-to-seal result bundles and run-record enrichment",
    ),
    Stage(
        issue=40,
        slug="functional_v1_scenarios",
        group="scenarios",
        proves="Functional V1 calibration packages lock deterministically with complete qualification evidence",
    ),
    Stage(
        issue=51,
        slug="proof_hardening",
        group="verification",
        proves="Acceptance Verification Artifact harness rejects partial selection, configuration failures, and stale outputs",
        docker=True,
        extra=("--require-docker", "--acceptance-input=tests/architecture"),
    ),
    Stage(
        issue=54,
        slug="verification_policy",
        group="verification",
        proves="Closed-world development verification policy and guarded development runs",
    ),
    Stage(
        issue=55,
        slug="digest_provisioning",
        group="provisioning",
        proves="Digest-first image provisioning: cold registry pull, then warm cache with zero registry traffic",
        docker=True,
    ),
    Stage(
        issue=74,
        slug="functional_v1_operator",
        group="operator",
        proves="Functional V1 operator: manifest validation, managed home, dispositions, and CLI",
    ),
    Stage(
        issue=118,
        slug="minimax_m3_manifest",
        group="operator",
        proves="MiniMax M3 Functional V1 manifest: sealed route, pricing, fixed matrix, and canonical identities",
        extra=("--acceptance-input=functional-v1-minimax-m3.yaml",),
    ),
    Stage(
        issue=123,
        slug="hy3_manifest",
        group="operator",
        proves="Hy3 Functional V1 manifest: sealed route, pricing, fixed matrix, and canonical identities",
        extra=("--acceptance-input=functional-v1-hy3.yaml",),
    ),
    Stage(
        issue=120,
        slug="react_author_filter",
        group="scenarios",
        proves="React author-filter package: immutable provenance, bounded submission, and isolated behavioral qualification",
        docker=True,
    ),
)


@dataclass
class StageResult:
    stage: Stage
    outcome: str
    seconds: float = 0.0
    artifacts: tuple[str, ...] = field(default_factory=tuple)


def validate_layout(acceptance_root: Path, stages: tuple[Stage, ...]) -> None:
    declared = {stage.directory for stage in stages}
    if len(declared) != len(stages):
        raise SuiteLayoutError("stage manifest declares a directory twice")
    issues = {stage.issue for stage in stages}
    if len(issues) != len(stages):
        raise SuiteLayoutError("stage manifest declares an issue twice")
    on_disk = {
        entry.name
        for entry in acceptance_root.iterdir()
        if entry.is_dir() and entry.name.startswith("issue_")
    }
    missing = sorted(declared - on_disk)
    unknown = sorted(on_disk - declared)
    if missing or unknown:
        raise SuiteLayoutError(
            "stage manifest and tests/acceptance drifted; "
            f"missing on disk: {missing or 'none'}; "
            f"not declared: {unknown or 'none'}"
        )


def select_stages(
    stages: tuple[Stage, ...],
    only: str | None,
    start: str | None,
) -> tuple[Stage, ...]:
    selected = list(stages)
    if start is not None:
        index = next(
            (i for i, stage in enumerate(selected) if _matches(stage, start)), None
        )
        if index is None:
            raise SuiteLayoutError(f"unknown --from stage: {start}")
        selected = selected[index:]
    if only is not None:
        tokens = [token.strip() for token in only.split(",") if token.strip()]
        if not tokens:
            raise SuiteLayoutError("--only requires at least one stage token")
        chosen: list[Stage] = []
        for token in tokens:
            matches = [stage for stage in selected if _matches(stage, token)]
            if not matches:
                raise SuiteLayoutError(f"unknown --only stage: {token}")
            chosen.extend(match for match in matches if match not in chosen)
        selected = [stage for stage in selected if stage in chosen]
    return tuple(selected)


def _matches(stage: Stage, token: str) -> bool:
    return token in (str(stage.issue), stage.slug, stage.directory)


def pytest_command(stage: Stage) -> list[str]:
    return [
        str(_pytest_script()),
        "-q",
        stage.path,
        "--maxfail=1",
        "-p",
        "no:cacheprovider",
        *stage.extra,
    ]


def _pytest_script() -> Path:
    script = Path(sys.executable).with_name("pytest")
    if not script.is_file():
        raise SuiteLayoutError(
            "pytest launcher not found next to the interpreter; run the suite "
            "inside the project environment (uv run python scripts/acceptance.py)"
        )
    return script


def assert_docker_available(stages: tuple[Stage, ...]) -> None:
    needing = [stage for stage in stages if stage.docker]
    if not needing:
        return
    docker = shutil.which("docker")
    probe = (
        subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if docker is not None
        else None
    )
    if probe is None or probe.returncode != 0:
        issues = ", ".join(str(stage.issue) for stage in needing)
        raise SuiteLayoutError(
            f"issues {issues} require a responding Docker daemon; start one or "
            "deselect them with --only/--from"
        )


def _artifact_paths(stage: Stage) -> tuple[str, ...]:
    root = PROJECT_ROOT / f"artifacts/acceptance/issue-{stage.issue}"
    return tuple(
        str(path.relative_to(PROJECT_ROOT))
        for path in (root / "verification.json", root / "sha256sums.txt")
        if path.is_file()
    )


def run_suite(selected: tuple[Stage, ...], keep_going: bool) -> list[StageResult]:
    results: list[StageResult] = []
    for stage in selected:
        print(f"=== issue {stage.issue} [{stage.group}] {stage.path}", flush=True)
        started = time.monotonic()
        completed = subprocess.run(pytest_command(stage), cwd=PROJECT_ROOT, check=False)
        elapsed = time.monotonic() - started
        passed = completed.returncode == 0
        artifacts = _artifact_paths(stage) if passed else ()
        outcome = "passed" if passed and len(artifacts) == 2 else "failed"
        results.append(StageResult(stage, outcome, elapsed, artifacts))
        if outcome == "failed" and not keep_going:
            remaining = selected[len(results) :]
            results.extend(StageResult(stage, "not-run") for stage in remaining)
            break
    return results


def print_plan(stages: tuple[Stage, ...]) -> None:
    for order, stage in enumerate(stages, start=1):
        docker = " [docker]" if stage.docker else ""
        print(f"{order:2d}. issue {stage.issue:<3d} {stage.path}{docker}")
        print(f"    {stage.proves}")


def print_summary(results: list[StageResult]) -> None:
    print("\n=== acceptance suite summary ===")
    width = max(len(result.stage.directory) for result in results)
    for result in results:
        line = (
            f"{result.outcome:>7s}  issue {result.stage.issue:<3d} "
            f"{result.stage.directory:<{width}s}"
        )
        if result.outcome != "not-run":
            line += f"  {result.seconds:7.1f}s"
        print(line)
        for artifact in result.artifacts:
            print(f"{'':9s}{artifact}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the ordered Acceptance Verification Artifact suite."
    )
    parser.add_argument(
        "--list", action="store_true", help="print the run plan and exit"
    )
    parser.add_argument(
        "--only",
        metavar="STAGE[,STAGE...]",
        help="run only these stages (issue number, slug, or directory name)",
    )
    parser.add_argument(
        "--from",
        dest="start",
        metavar="STAGE",
        help="start the ordered suite at this stage",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continue past a failed stage instead of stopping",
    )
    arguments = parser.parse_args(argv)

    try:
        validate_layout(ACCEPTANCE_ROOT, STAGES)
        selected = select_stages(STAGES, arguments.only, arguments.start)
        if arguments.list:
            print_plan(selected)
            return 0
        assert_docker_available(selected)
    except SuiteLayoutError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    results = run_suite(selected, arguments.keep_going)
    print_summary(results)
    return 0 if all(result.outcome == "passed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
