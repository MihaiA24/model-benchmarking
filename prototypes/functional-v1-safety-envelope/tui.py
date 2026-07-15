"""PROTOTYPE — run with:

    uv run python prototypes/functional-v1-safety-envelope/tui.py

Drive the candidate capacity and one-attempt state model by hand. Nothing persists.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

from model import (
    Action,
    CANDIDATE_DEFAULTS,
    CANDIDATE_HARD_CAPS,
    Envelope,
    HostProfile,
    PrototypeState,
    capacity_for,
    reduce,
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def _docker_info() -> tuple[str, str, int, int, str]:
    completed = subprocess.run(
        [
            "docker",
            "info",
            "--format",
            "{{.OperatingSystem}}\t{{.Architecture}}\t{{.NCPU}}\t{{.MemTotal}}\t{{.Driver}}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    engine, architecture, cpus, memory_bytes, driver = completed.stdout.strip().split(
        "\t"
    )
    return engine, architecture, int(cpus), int(memory_bytes), driver


def _probe_storage_quota() -> tuple[bool, str]:
    image = "alpine:3.20"
    inspected = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        timeout=10,
    )
    if inspected.returncode != 0:
        return False, f"storage quota probe unavailable: cached {image} is absent"
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--storage-opt",
            "size=16M",
            image,
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode == 0:
        return True, "Docker writable-layer quota probe passed"
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    reason = detail[0] if detail else f"Docker exited {completed.returncode}"
    return False, f"Docker writable-layer quota probe failed: {reason}"


def observed_host() -> HostProfile:
    try:
        engine, architecture, cpus, memory_bytes, driver = _docker_info()
        platform_arch = "arm64" if architecture in {"aarch64", "arm64"} else architecture
        storage_quota, storage_note = _probe_storage_quota()
        disk_free_mib = shutil.disk_usage(Path.cwd()).free // (1024 * 1024)
        return HostProfile(
            profile_id="observed-local",
            label="Observed current Docker host",
            container_platform=f"linux/{platform_arch}",
            cpu_cores=cpus,
            memory_mib=memory_bytes // (1024 * 1024),
            writable_disk_free_mib=disk_free_mib,
            engine=f"{engine} / {driver}",
            hard_storage_quota=storage_quota,
            qualified_egress_backend=False,
            observed=True,
            notes=(
                storage_note,
                "current engine has no qualified guarded-public-web backend yet",
            ),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return HostProfile(
            profile_id="observed-local-unavailable",
            label="Observed current Docker host",
            container_platform="unavailable",
            cpu_cores=0,
            memory_mib=0,
            writable_disk_free_mib=0,
            engine="unavailable",
            hard_storage_quota=False,
            qualified_egress_backend=False,
            observed=True,
            notes=(f"Docker host detection failed: {error}",),
        )


def representative_linux() -> HostProfile:
    return HostProfile(
        profile_id="representative-linux-amd64",
        label="Representative qualified Linux/amd64 floor",
        container_platform="linux/amd64",
        cpu_cores=8,
        memory_mib=16_384,
        writable_disk_free_mib=102_400,
        engine="native Docker / cgroup v2 / quota-capable storage",
        hard_storage_quota=True,
        qualified_egress_backend=True,
        observed=False,
        notes=(
            "modeled contract floor, not a measurement from this workstation",
            "requires native quota and guarded-egress qualification before use",
        ),
    )


def _value(value: object) -> str:
    if hasattr(value, "quantize"):
        return f"${value}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _envelope_lines(title: str, envelope: Envelope) -> list[str]:
    result = [f"{BOLD}{title}{RESET}"]
    for field in fields(envelope):
        result.append(f"  {field.name}: {_value(getattr(envelope, field.name))}")
    return result


def _cell_line(index: int, cell) -> str:
    symbol = {
        "planned": "·",
        "running": ">",
        "interrupted": "!",
        "terminal": "✓" if cell.disposition in {
            "valid_completed",
            "valid_harness_outcome",
            "valid_limit_outcome",
        } else "×",
    }[cell.phase]
    outcome = cell.disposition or cell.phase
    return f"  {index + 1:02d} {symbol} {cell.key:<48} {outcome}"


def render(state: PrototypeState) -> None:
    if sys.stdout.isatty():
        print("\x1b[2J\x1b[H", end="")
    capacity = capacity_for(state.host, state.envelope)
    print(f"{BOLD}Functional V1 safety-envelope prototype{RESET}")
    print(f"{DIM}Throwaway: capacity admission, fail-closed scheduling, and resume semantics{RESET}\n")
    print(f"{BOLD}Host{RESET}")
    print(f"  {state.host.label} ({'observed' if state.host.observed else 'modeled'})")
    print(f"  platform={state.host.container_platform} engine={state.host.engine}")
    print(
        f"  cpu={state.host.cpu_cores} memory={state.host.memory_mib:,} MiB "
        f"free_disk={state.host.writable_disk_free_mib:,} MiB"
    )
    print(
        f"  hard_storage_quota={state.host.hard_storage_quota} "
        f"qualified_egress={state.host.qualified_egress_backend}"
    )
    for note in state.host.notes:
        print(f"  {DIM}{note}{RESET}")

    print(f"\n{BOLD}Selected envelope{RESET}")
    for field in fields(state.envelope):
        print(f"  {field.name}: {_value(getattr(state.envelope, field.name))}")
    print(
        "  capacity: "
        f"cpu={capacity.by_cpu} memory={capacity.by_memory} disk={capacity.by_disk} "
        f"=> safe_parallel={capacity.safe_parallel}"
    )
    print(
        "  reserves: cpu=2 memory=2,048 MiB disk=10,240 MiB; "
        "per-slot overhead: memory=1,024 MiB disk=1,024 MiB"
    )

    print(f"\n{BOLD}Preflight and run{RESET}")
    print(
        f"  scheduler={state.scheduler} run_state={state.run_state} "
        f"validity={state.validity}"
    )
    if state.preflight:
        print(f"  preflight={'PASS' if state.preflight.passed else 'REJECT'}")
        for failure in state.preflight.failures:
            print(f"    × {failure}")
        for warning in state.preflight.warnings:
            print(f"    ! {warning}")

    print(f"\n{BOLD}Cells{RESET}")
    for index, cell in enumerate(state.cells):
        print(_cell_line(index, cell))

    print(f"\n{BOLD}Recent transitions{RESET}")
    for event in state.events or ("none",):
        print(f"  {event}")

    print(f"\n{BOLD}Actions{RESET}")
    print("  [1] observed host  [2] Linux floor  [d] defaults  [h] field hard caps")
    print("  [[] parallel -     []] parallel +  [p] preflight [s] schedule")
    print("  [c] complete        [f] harness     [l] limit     [i] infrastructure")
    print("  [x] integrity       [o] operator    [k] crash     [r] resume")
    print("  [n] reset           [v] values      [q] quit")


def show_values() -> None:
    print()
    for line in _envelope_lines("Candidate defaults", CANDIDATE_DEFAULTS):
        print(line)
    print()
    for line in _envelope_lines("Candidate per-field hard caps", CANDIDATE_HARD_CAPS):
        print(line)
    input("\nEnter to return: ")


def main() -> int:
    current = observed_host()
    linux = representative_linux()
    state = PrototypeState(host=current)
    actions = {
        "1": lambda: Action("select_host", host=current),
        "2": lambda: Action("select_host", host=linux),
        "d": lambda: Action("defaults"),
        "h": lambda: Action("hard_caps"),
        "[": lambda: Action("parallel_down"),
        "]": lambda: Action("parallel_up"),
        "p": lambda: Action("preflight"),
        "s": lambda: Action("schedule"),
        "c": lambda: Action("complete"),
        "f": lambda: Action("harness"),
        "l": lambda: Action("limit"),
        "i": lambda: Action("infrastructure"),
        "x": lambda: Action("integrity"),
        "o": lambda: Action("operator_abort"),
        "k": lambda: Action("crash"),
        "r": lambda: Action("resume"),
        "n": lambda: Action("reset"),
    }
    while True:
        render(state)
        try:
            key = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if key == "q":
            return 0
        if key == "v":
            show_values()
            continue
        factory = actions.get(key)
        state = reduce(state, factory() if factory else Action(key))


if __name__ == "__main__":
    raise SystemExit(main())
