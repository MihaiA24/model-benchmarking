from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_benchmark import __version__
from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.scenarios import (
    ScenarioPackage,
    ScenarioPackageError,
    check_scenario_package,
    lock_scenario_package,
    scaffold_scenario_package,
)
from model_benchmark.evidence.capture import trusted_capture_source


def _configure_scenario_parser(parser: argparse.ArgumentParser) -> None:
    subcommands = parser.add_subparsers(dest="scenario_command", required=True)
    scaffold = subcommands.add_parser(
        "scaffold", help="create a standard-v1 Scenario Package"
    )
    scaffold.add_argument("path", type=Path)
    scaffold.add_argument("--scenario-id", required=True)
    scaffold.add_argument(
        "--ecosystem",
        required=True,
        choices=(
            "angular-typescript",
            "spring-boot-java",
            "python-data-engineering",
        ),
    )
    scaffold.add_argument("--visibility", required=True, choices=("public", "private"))
    check = subcommands.add_parser("check", help="validate a Scenario Package")
    check.add_argument("path", type=Path)
    qualify = subcommands.add_parser(
        "qualify", help="provision, measure, or seal a locked Scenario Package"
    )
    qualify.add_argument("path", type=Path)
    qualify.add_argument("--provision", action="store_true")
    qualify.add_argument(
        "--preflight", choices=("integration", "qualification", "measured")
    )
    qualify.add_argument("--jobs-dir", type=Path)
    qualify.add_argument("--target-config", type=Path)
    qualify.add_argument("--qualification-record", type=Path)
    qualify.add_argument("--provisioning-manifest", type=Path)
    qualify.add_argument("--preflight-output", type=Path)
    qualify.add_argument("--measure-output", type=Path)
    qualify.add_argument("--worker-private-key", type=Path)
    qualify.add_argument("--max-parallel", type=int, choices=(1, 2, 3))
    qualify.add_argument("--technical-evidence", type=Path)
    qualify.add_argument("--trusted-worker-identity")
    qualify.add_argument("--review", type=Path)
    qualify.add_argument("--trusted-reviewer-identity")
    qualify.add_argument("--output", type=Path)
    lock = subcommands.add_parser("lock", help="seal a deterministic package lock")
    lock.add_argument("path", type=Path)


def _emit(summary: dict[str, object], machine_readable: bool) -> None:
    if machine_readable:
        sys.stdout.buffer.write(canonical_json_bytes(summary) + b"\n")
    else:
        print(summary["message"])


def _run_scenario(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.scenario_command == "scaffold":
        return scaffold_scenario_package(
            path=arguments.path,
            scenario_id=arguments.scenario_id,
            ecosystem=arguments.ecosystem,
            visibility=arguments.visibility,
            trusted_capture_source=trusted_capture_source(),
        )
    if arguments.scenario_command == "check":
        return check_scenario_package(arguments.path)
    if arguments.scenario_command == "lock":
        return lock_scenario_package(arguments.path)
    if arguments.scenario_command == "qualify":
        package = ScenarioPackage.open(arguments.path)
        seal_fields = (
            "technical_evidence",
            "trusted_worker_identity",
            "review",
            "trusted_reviewer_identity",
            "output",
        )
        seal_requested = any(
            getattr(arguments, field) is not None for field in seal_fields
        )
        selected_phases = sum(
            (
                arguments.provision,
                arguments.preflight is not None,
                arguments.measure_output is not None,
                seal_requested,
            )
        )
        if selected_phases != 1:
            raise ScenarioPackageError(
                "invalid-qualification-arguments",
                "scenario qualify requires exactly one of --provision, --preflight, --measure-output, or sealing arguments",
            )
        if arguments.provision:
            if any(
                value is None
                for value in (
                    arguments.jobs_dir,
                    arguments.target_config,
                    arguments.provisioning_manifest,
                )
            ):
                raise ScenarioPackageError(
                    "invalid-qualification-arguments",
                    "--provision requires --jobs-dir, --target-config, and --provisioning-manifest",
                )
            from model_benchmark.runtime.scenario_qualification import (
                provision_scenario_package,
            )

            return provision_scenario_package(
                package.root,
                jobs_dir=arguments.jobs_dir,
                manifest_output=arguments.provisioning_manifest,
                target_config=arguments.target_config,
                qualification_record=arguments.qualification_record,
            )
        if arguments.preflight is not None:
            if (
                arguments.provisioning_manifest is None
                or arguments.preflight_output is None
                or arguments.preflight == "measured"
                and arguments.qualification_record is None
            ):
                raise ScenarioPackageError(
                    "invalid-qualification-arguments",
                    "--preflight requires --provisioning-manifest and --preflight-output; measured preflight also requires --qualification-record",
                )
            from model_benchmark.runtime.provisioning import preflight

            return preflight(
                package.root,
                manifest_path=arguments.provisioning_manifest,
                mode=arguments.preflight,
                output=arguments.preflight_output,
                qualification_record=arguments.qualification_record,
            )
        if arguments.max_parallel is not None and arguments.measure_output is None:
            raise ScenarioPackageError(
                "invalid-qualification-arguments",
                "--max-parallel is valid only with --measure-output",
            )
        if arguments.measure_output is not None:
            if any(
                value is None
                for value in (
                    arguments.jobs_dir,
                    arguments.worker_private_key,
                    arguments.provisioning_manifest,
                    arguments.preflight_output,
                )
            ):
                raise ScenarioPackageError(
                    "invalid-qualification-arguments",
                    "--measure-output requires --jobs-dir, --worker-private-key, --provisioning-manifest, and --preflight-output",
                )
            from model_benchmark.runtime.scenario_qualification import (
                measure_scenario_package,
            )

            return measure_scenario_package(
                package.root,
                jobs_dir=arguments.jobs_dir,
                output=arguments.measure_output,
                worker_private_key=arguments.worker_private_key,
                provisioning_manifest=arguments.provisioning_manifest,
                preflight_output=arguments.preflight_output,
                max_parallel=arguments.max_parallel or 1,
            )
        if any(
            value is None
            for value in (
                arguments.technical_evidence,
                arguments.trusted_worker_identity,
                arguments.review,
                arguments.trusted_reviewer_identity,
                arguments.output,
            )
        ):
            raise ScenarioPackageError(
                "invalid-qualification-arguments",
                "sealing requires --technical-evidence, --trusted-worker-identity, --review, --trusted-reviewer-identity, and --output",
            )
        return package.qualify(
            technical_evidence=arguments.technical_evidence,
            trusted_worker_identity=arguments.trusted_worker_identity,
            review=arguments.review,
            trusted_reviewer_identity=arguments.trusted_reviewer_identity,
            output=arguments.output,
        )
    raise ScenarioPackageError(
        "not-implemented",
        f"scenario {arguments.scenario_command} is not implemented",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the non-interactive operator command shell."""
    parser = argparse.ArgumentParser(
        prog="model-benchmark",
        description="Operate the reproducible coding-harness benchmark.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable canonical JSON summary",
    )
    commands = parser.add_subparsers(dest="command")
    _configure_scenario_parser(
        commands.add_parser("scenario", help="author and qualify Scenario Packages")
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "scenario":
        try:
            summary = _run_scenario(arguments)
        except ScenarioPackageError as error:
            if arguments.json:
                _emit(error.summary(), True)
            else:
                print(
                    f"scenario error [{error.classification}]: {error}", file=sys.stderr
                )
            return 2
        _emit(summary, arguments.json)
        return 0
    if arguments.json:
        summary = {
            "modules": ["analysis", "declarations", "evidence", "runtime"],
            "program": "model-benchmark",
            "status": "foundation-ready",
            "version": __version__,
        }
        sys.stdout.buffer.write(canonical_json_bytes(summary) + b"\n")
    else:
        print(f"model-benchmark {__version__} — foundation ready")
    return 0
