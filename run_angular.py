#!/usr/bin/env python3
"""Legacy entrypoint: run Angular tasks through the unified raw_api harness."""

from benchmark.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["--stack", "angular", "--harness", "raw_api"]))
