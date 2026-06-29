"""Build/test verification for benchmark workdirs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from benchmark.util import benchmark_env


def _run_command(cmd: list[str], *, cwd: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        command: str | list[str] = subprocess.list2cmdline([str(part) for part in cmd])
        shell = True
    else:
        command = [str(part) for part in cmd]
        shell = False
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=benchmark_env(),
        shell=shell,
    )


def run_build_check(workdir: Path, task, *, timeout_s: int) -> bool:
    build = _run_command(task.build_cmd, cwd=workdir, timeout_s=timeout_s)
    build_ok = build.returncode == 0
    if not build_ok:
        (workdir / "_build_output.txt").write_text((build.stdout or "") + (build.stderr or ""), encoding="utf-8")
    return build_ok


def run_checks(workdir: Path, task, *, timeout_s: int) -> tuple[bool, bool]:
    build_ok = run_build_check(workdir, task, timeout_s=timeout_s)

    if task.test_ok_equals_build:
        return build_ok, build_ok

    if not build_ok:
        return build_ok, False

    test = _run_command(task.test_cmd, cwd=workdir, timeout_s=timeout_s)
    test_ok = test.returncode == 0
    if not test_ok:
        (workdir / "_test_output.txt").write_text((test.stdout or "") + (test.stderr or ""), encoding="utf-8")
    return build_ok, test_ok
