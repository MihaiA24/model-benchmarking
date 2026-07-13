from __future__ import annotations

import argparse
import sys

from model_benchmark import __version__
from model_benchmark.declarations.canonical import canonical_json_bytes


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
    arguments = parser.parse_args(argv)
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
