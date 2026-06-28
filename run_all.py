#!/usr/bin/env python3
"""Lanza los 4 stacks en paralelo usando el runner central."""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

STACKS = [
    ("Spring Boot", "springboot"),
    ("Angular", "angular"),
    ("React", "react"),
    ("Datos", "data"),
]

HERE = pathlib.Path(__file__).parent.resolve()


def log_dir_for(args: argparse.Namespace) -> pathlib.Path:
    if args.results_dir:
        path = pathlib.Path(args.results_dir)
        return path if path.is_absolute() else HERE / path
    return HERE / "results"


def command_for(stack: str, args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(HERE / "run_benchmark.py"),
        "--stack",
        stack,
        "--harness",
        args.harness,
    ]
    if args.models is not None:
        cmd.extend(["--models", args.models])
    cmd.extend(["--runs", str(args.runs)])
    if args.results_dir:
        cmd.extend(["--results-dir", args.results_dir])
    for adapter_model in args.adapter_model or []:
        cmd.extend(["--adapter-model", adapter_model])
    if args.no_resume:
        cmd.append("--no-resume")
    if args.preflight:
        cmd.append("--preflight")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch all benchmark stacks through run_benchmark.py.")
    parser.add_argument("--harness", default="raw_api", help="Harness selector passed to run_benchmark.py")
    parser.add_argument("--models", default=None, help="Model selector passed to run_benchmark.py; omit to use BENCHMARK_MODELS from .env/env, then new")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--results-dir", help="Results directory passed to run_benchmark.py")
    parser.add_argument("--adapter-model", action="append", help="Repeatable harness=model selector override")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait", action="store_true", help="Wait for all stacks and return non-zero if any fails")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model_source = args.models if args.models not in (None, "") else "BENCHMARK_MODELS/.env"
    results_dir = args.results_dir or "results"
    print(f"Lanzando 4 stacks en paralelo con harness={args.harness}, models={model_source}, results_dir={results_dir}...")
    processes: list[tuple[str, str, subprocess.Popen, object | None]] = []
    for title, stack in STACKS:
        cmd = command_for(stack, args)
        log_handle = None
        if os.name == "nt" and not args.wait:
            quoted = subprocess.list2cmdline(cmd)
            command = f'start "{title}" cmd /k "{quoted} & echo. & echo Terminado. Pulsa ENTER para cerrar. & pause"'
            process = subprocess.Popen(command, shell=True, cwd=str(HERE))
            log_path = "cmd window"
        else:
            log_path = log_dir_for(args) / f"run_all_{stack}.log"
            log_path.parent.mkdir(exist_ok=True)
            log_handle = open(log_path, "w", encoding="utf-8")
            process = subprocess.Popen(cmd, cwd=str(HERE), stdout=log_handle, stderr=subprocess.STDOUT)
        print(f"  {title}: pid={process.pid}, log={log_path}")
        processes.append((title, stack, process, log_handle))
        time.sleep(0.5)

    if not args.wait:
        print("Hecho. Cuando terminen, ejecuta: python merge_metrics.py")
        return 0

    failed: list[str] = []
    for title, _, process, log_handle in processes:
        code = process.wait()
        if log_handle is not None:
            log_handle.close()
        if code != 0:
            failed.append(f"{title}={code}")
    if failed:
        print("Fallo: " + ", ".join(failed))
        return 1
    print("Todos los stacks terminaron OK. Ejecuta: python merge_metrics.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
