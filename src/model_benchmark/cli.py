from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.functional_v1 import (
    FunctionalV1Manifest,
    FunctionalV1ManifestError,
)
from model_benchmark.runtime.functional_v1 import (
    CommandResult,
    FunctionalV1Home,
    FunctionalV1HomeError,
    RuntimeFactory,
    default_runtime,
)


class _CliUsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CliUsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="model-benchmark",
        description="Operate one local Functional V1 benchmark.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path(".model-benchmark"),
        help="managed Functional V1 Home (default: .model-benchmark)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit exactly one canonical JSON document",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    provision = commands.add_parser(
        "provision",
        help="provision immutable inputs for one Run Manifest",
    )
    provision.add_argument("manifest", type=Path)

    preflight = commands.add_parser(
        "preflight",
        help="run network-disabled, cache-read-only checks",
    )
    preflight.add_argument("manifest", type=Path)

    run = commands.add_parser("run", help="start or narrowly resume one Functional V1 Run")
    run_inputs = run.add_mutually_exclusive_group(required=True)
    run_inputs.add_argument("manifest", type=Path, nargs="?")
    run_inputs.add_argument("--resume", metavar="RUN_ID")

    inspect = commands.add_parser("inspect", help="verify and inspect one sealed Run Record")
    inspect.add_argument("run_id")
    return parser


def _emit_json(payload: dict[str, object]) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(payload) + b"\n")


def _emit_result(result: CommandResult, machine_readable: bool) -> int:
    if machine_readable:
        _emit_json(dict(result.payload))
    else:
        print(result.human)
    return result.exit_code


def _emit_rejection(
    payload: dict[str, object],
    *,
    message: str,
    machine_readable: bool,
    exit_code: int,
) -> int:
    if machine_readable:
        _emit_json(payload)
    else:
        print(message, file=sys.stderr)
    return exit_code


def main(
    argv: list[str] | None = None,
    *,
    runtime_factory: RuntimeFactory = default_runtime,
) -> int:
    """Run the strict non-interactive Functional V1 operator shell."""
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    machine_readable = "--json" in raw_arguments
    parser = _parser()
    try:
        arguments = parser.parse_args(raw_arguments)
    except _CliUsageError as error:
        return _emit_rejection(
            {
                "command": "cli",
                "message": str(error),
                "outcome": "rejected",
                "reason_code": "invalid-cli-usage",
            },
            message=f"usage error: {error}",
            machine_readable=machine_readable,
            exit_code=2,
        )

    command = arguments.command
    try:
        home = FunctionalV1Home(arguments.home)
        runtime = runtime_factory(home)
        if command == "inspect":
            result = runtime.inspect(arguments.run_id)
        elif command == "run" and getattr(arguments, "resume", None) is not None:
            result = runtime.resume(arguments.resume)
        else:
            manifest = FunctionalV1Manifest.load(arguments.manifest)
            if command == "provision":
                result = runtime.provision(manifest)
            elif command == "preflight":
                result = runtime.preflight(manifest)
            else:
                result = runtime.run(manifest)
    except FunctionalV1ManifestError as error:
        return _emit_rejection(
            error.summary(command),
            message=f"manifest error [{error.reason_code}]: {error}",
            machine_readable=arguments.json,
            exit_code=2,
        )
    except FunctionalV1HomeError as error:
        exit_code = 1 if command == "inspect" or getattr(arguments, "resume", None) is not None else 3
        return _emit_rejection(
            error.summary(command),
            message=f"{command} error [{error.reason_code}]: {error}",
            machine_readable=arguments.json,
            exit_code=exit_code,
        )
    return _emit_result(result, arguments.json)
