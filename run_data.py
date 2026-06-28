#!/usr/bin/env python3
"""Legacy entrypoint: run Data tasks through the unified raw_api harness."""

from benchmark.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["--stack", "data", "--harness", "raw_api"]))
