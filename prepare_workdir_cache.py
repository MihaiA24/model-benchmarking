#!/usr/bin/env python3
"""Prepare seeded copy-on-write benchmark workdir snapshots."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark.runner import expand_stacks, select_tasks
from benchmark.util import repo_path
from benchmark.workdir import prepare_task_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy benchmark task baselines into a reusable snapshot cache."
    )
    parser.add_argument("--stack", default="all", help="Comma-separated stacks: springboot,angular,react,data,all")
    parser.add_argument("--task", action="append", help="Prepare only this task id. Repeatable.")
    parser.add_argument("--cache-dir", default=".benchmark-cache/task-snapshots", help="Repo-relative or absolute snapshot cache path")
    parser.add_argument("--refresh", action="store_true", help="Rebuild snapshots even when they already exist")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache_dir = repo_path(Path(args.cache_dir))
    stacks = expand_stacks(args.stack)
    tasks = select_tasks(stacks, args.task)

    for task in tasks:
        snapshot = prepare_task_snapshot(task, cache_dir, refresh=args.refresh)
        print(f"{task.name:32} -> {snapshot}")

    print(f"Prepared {len(tasks)} task snapshots in {cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
