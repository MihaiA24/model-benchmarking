from __future__ import annotations

import argparse
from pathlib import Path

from model_benchmark.runtime import (
    hermes_mounted_launch,
    omp_launch,
    opencode_launch,
    raw_api_launch,
)


_MOUNT = Path("/opt/model-benchmark-condition")
_INVALID_INVOCATION_EXIT = 78


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--condition", choices=("omp", "opencode", "hermes", "raw-api"), required=True
    )
    parser.add_argument("--artifact-identity", required=True)
    parser.add_argument("--target-path", default="")
    arguments = parser.parse_args(argv)
    common = ["--artifact-identity", arguments.artifact_identity]
    if arguments.condition == "omp":
        return omp_launch.main(["--omp", str(_MOUNT / "artifact/omp"), *common])
    if arguments.condition == "opencode":
        return opencode_launch.main(
            ["--opencode", str(_MOUNT / "artifact/opencode"), *common]
        )
    if arguments.condition == "hermes":
        return hermes_mounted_launch.main(common)
    if not arguments.target_path:
        return _INVALID_INVOCATION_EXIT
    return raw_api_launch.main([*common, "--target-path", arguments.target_path])


if __name__ == "__main__":
    raise SystemExit(main())
