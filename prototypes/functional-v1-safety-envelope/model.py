"""PROTOTYPE — discard after the Functional V1 envelope decision.

Question: do the proposed capacity-preflight calculation, one-attempt cell states,
global fail-closed transition, and candidate limit values form a small enough local
scheduler contract for Functional V1 on the current Apple Silicon workstation and
a representative native Linux/amd64 worker?

This module is pure. The terminal shell in ``tui.py`` owns all I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal


SCENARIOS = (
    "python-sales-by-genre",
    "spring-petvalidator-whitespace",
    "angular-reading-time",
)
CONDITIONS = ("omp", "opencode", "hermes", "raw-api")
CELL_KEYS = tuple(
    f"{scenario}/{condition}"
    for scenario in SCENARIOS
    for condition in CONDITIONS
)
VALID_DISPOSITIONS = {
    "valid_completed",
    "valid_harness_outcome",
    "valid_limit_outcome",
}

GLOBAL_CPU_RESERVE = 2
GLOBAL_MEMORY_RESERVE_MIB = 2_048
GLOBAL_DISK_RESERVE_MIB = 10_240
PER_SLOT_MEMORY_OVERHEAD_MIB = 1_024
PER_SLOT_DISK_OVERHEAD_MIB = 1_024


@dataclass(frozen=True)
class Envelope:
    max_parallel: int
    cpu_cores_per_trial: int
    memory_mib_per_trial: int
    writable_disk_mib_per_trial: int
    wall_time_seconds_per_trial: int
    requests_per_trial: int
    provider_tokens_per_trial: int
    stop_after_cost_usd_per_trial: Decimal


CANDIDATE_DEFAULTS = Envelope(
    max_parallel=2,
    cpu_cores_per_trial=2,
    memory_mib_per_trial=4_096,
    writable_disk_mib_per_trial=8_192,
    wall_time_seconds_per_trial=2_700,
    requests_per_trial=64,
    provider_tokens_per_trial=500_000,
    stop_after_cost_usd_per_trial=Decimal("5.00"),
)

CANDIDATE_HARD_CAPS = Envelope(
    max_parallel=2,
    cpu_cores_per_trial=4,
    memory_mib_per_trial=8_192,
    writable_disk_mib_per_trial=16_384,
    wall_time_seconds_per_trial=7_200,
    requests_per_trial=128,
    provider_tokens_per_trial=1_000_000,
    stop_after_cost_usd_per_trial=Decimal("20.00"),
)


@dataclass(frozen=True)
class HostProfile:
    profile_id: str
    label: str
    container_platform: str
    cpu_cores: int
    memory_mib: int
    writable_disk_free_mib: int
    engine: str
    hard_storage_quota: bool
    qualified_egress_backend: bool
    observed: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Capacity:
    by_cpu: int
    by_memory: int
    by_disk: int
    safe_parallel: int


@dataclass(frozen=True)
class PreflightReport:
    passed: bool
    capacity: Capacity
    failures: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Cell:
    key: str
    phase: Literal["planned", "running", "interrupted", "terminal"] = "planned"
    disposition: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PrototypeState:
    host: HostProfile
    envelope: Envelope = CANDIDATE_DEFAULTS
    cells: tuple[Cell, ...] = tuple(Cell(key) for key in CELL_KEYS)
    scheduler: Literal[
        "idle",
        "ready",
        "running",
        "operator-stopped",
        "crashed",
        "sealed",
    ] = "idle"
    preflight: PreflightReport | None = None
    run_state: Literal["unstarted", "unsealed", "complete", "incomplete"] = "unstarted"
    validity: Literal["unknown", "valid", "invalid"] = "unknown"
    events: tuple[str, ...] = ()


@dataclass(frozen=True)
class Action:
    kind: str
    host: HostProfile | None = None


def capacity_for(host: HostProfile, envelope: Envelope) -> Capacity:
    available_cpu = max(0, host.cpu_cores - GLOBAL_CPU_RESERVE)
    available_memory = max(0, host.memory_mib - GLOBAL_MEMORY_RESERVE_MIB)
    available_disk = max(0, host.writable_disk_free_mib - GLOBAL_DISK_RESERVE_MIB)
    by_cpu = available_cpu // max(1, envelope.cpu_cores_per_trial)
    by_memory = available_memory // max(
        1, envelope.memory_mib_per_trial + PER_SLOT_MEMORY_OVERHEAD_MIB
    )
    by_disk = available_disk // max(
        1, envelope.writable_disk_mib_per_trial + PER_SLOT_DISK_OVERHEAD_MIB
    )
    return Capacity(
        by_cpu=by_cpu,
        by_memory=by_memory,
        by_disk=by_disk,
        safe_parallel=min(by_cpu, by_memory, by_disk),
    )


def _positive_integer_fields(envelope: Envelope) -> tuple[tuple[str, int], ...]:
    return (
        ("max_parallel", envelope.max_parallel),
        ("cpu_cores_per_trial", envelope.cpu_cores_per_trial),
        ("memory_mib_per_trial", envelope.memory_mib_per_trial),
        ("writable_disk_mib_per_trial", envelope.writable_disk_mib_per_trial),
        ("wall_time_seconds_per_trial", envelope.wall_time_seconds_per_trial),
        ("requests_per_trial", envelope.requests_per_trial),
        ("provider_tokens_per_trial", envelope.provider_tokens_per_trial),
    )


def preflight(host: HostProfile, envelope: Envelope) -> PreflightReport:
    failures: list[str] = []
    warnings: list[str] = []
    for name, value in _positive_integer_fields(envelope):
        if value < 1:
            failures.append(f"{name} must be positive")
    if envelope.stop_after_cost_usd_per_trial <= 0:
        failures.append("stop_after_cost_usd_per_trial must be positive")

    for name, value in _positive_integer_fields(envelope):
        cap = getattr(CANDIDATE_HARD_CAPS, name)
        if value > cap:
            failures.append(f"{name}={value} exceeds candidate hard cap {cap}")
    if (
        envelope.stop_after_cost_usd_per_trial
        > CANDIDATE_HARD_CAPS.stop_after_cost_usd_per_trial
    ):
        failures.append(
            "stop_after_cost_usd_per_trial exceeds candidate hard cap "
            f"{CANDIDATE_HARD_CAPS.stop_after_cost_usd_per_trial}"
        )

    if host.container_platform not in {"linux/arm64", "linux/amd64"}:
        failures.append(f"unsupported container platform {host.container_platform}")
    if not host.hard_storage_quota:
        failures.append("writable-disk hard enforcement unavailable")
    if not host.qualified_egress_backend:
        failures.append("guarded-public-web enforcement backend is not qualified")

    capacity = capacity_for(host, envelope)
    if envelope.max_parallel > capacity.safe_parallel:
        failures.append(
            f"max_parallel={envelope.max_parallel} exceeds safe capacity "
            f"{capacity.safe_parallel} (cpu={capacity.by_cpu}, "
            f"memory={capacity.by_memory}, disk={capacity.by_disk})"
        )

    warnings.append(
        "provider token and cost thresholds apply after responses; one request may overshoot"
    )
    warnings.append(
        "declared matrix spend threshold is "
        f"${envelope.stop_after_cost_usd_per_trial * len(CELL_KEYS):.2f} plus overshoot"
    )
    return PreflightReport(
        passed=not failures,
        capacity=capacity,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )


def _event(state: PrototypeState, message: str) -> PrototypeState:
    return replace(state, events=(*state.events[-5:], message))


def _replace_cells(state: PrototypeState, cells: list[Cell]) -> PrototypeState:
    return replace(state, cells=tuple(cells))


def _terminalize_first_running(
    state: PrototypeState, disposition: str, reason: str
) -> PrototypeState:
    cells = list(state.cells)
    for index, cell in enumerate(cells):
        if cell.phase == "running":
            cells[index] = replace(
                cell,
                phase="terminal",
                disposition=disposition,
                reason=reason,
            )
            state = _replace_cells(state, cells)
            return _event(state, f"terminal {cell.key}: {disposition}")
    return _event(state, "no running cell to finish")


def _seal_if_complete(state: PrototypeState) -> PrototypeState:
    if all(cell.phase == "terminal" for cell in state.cells):
        valid = all(cell.disposition in VALID_DISPOSITIONS for cell in state.cells)
        return _event(
            replace(
                state,
                scheduler="sealed",
                run_state="complete",
                validity="valid" if valid else "invalid",
            ),
            "sealed complete Run Record",
        )
    return state


def _global_abort(
    state: PrototypeState, disposition: str, reason: str
) -> PrototypeState:
    cells = [
        replace(
            cell,
            phase="terminal",
            disposition=disposition,
            reason=reason,
        )
        if cell.phase in {"running", "interrupted"}
        else cell
        for cell in state.cells
    ]
    state = replace(
        state,
        cells=tuple(cells),
        scheduler="sealed",
        run_state="incomplete",
        validity="invalid",
    )
    return _event(state, f"global fail-closed: {disposition} ({reason})")


def reduce(state: PrototypeState, action: Action) -> PrototypeState:
    if action.kind == "reset":
        return PrototypeState(host=state.host)
    if action.kind == "select_host" and action.host is not None:
        return PrototypeState(host=action.host)
    if action.kind == "defaults":
        return _event(
            replace(state, envelope=CANDIDATE_DEFAULTS, preflight=None),
            "loaded candidate defaults",
        )
    if action.kind == "hard_caps":
        return _event(
            replace(state, envelope=CANDIDATE_HARD_CAPS, preflight=None),
            "loaded candidate per-field hard caps",
        )
    if action.kind in {"parallel_down", "parallel_up"}:
        delta = -1 if action.kind == "parallel_down" else 1
        envelope = replace(
            state.envelope,
            max_parallel=max(1, state.envelope.max_parallel + delta),
        )
        return _event(
            replace(state, envelope=envelope, preflight=None),
            f"set max_parallel={envelope.max_parallel}",
        )
    if action.kind == "preflight":
        report = preflight(state.host, state.envelope)
        return _event(
            replace(
                state,
                preflight=report,
                scheduler="ready" if report.passed else "idle",
                run_state="unstarted",
                validity="unknown",
            ),
            "preflight passed" if report.passed else "preflight rejected",
        )
    if action.kind == "schedule":
        if state.scheduler not in {"ready", "running"} or not state.preflight:
            return _event(state, "schedule rejected: fresh preflight required")
        if not state.preflight.passed:
            return _event(state, "schedule rejected: preflight failed")
        running = sum(cell.phase == "running" for cell in state.cells)
        available = max(0, state.envelope.max_parallel - running)
        cells = list(state.cells)
        started: list[str] = []
        for index, cell in enumerate(cells):
            if available == 0:
                break
            if cell.phase == "planned":
                cells[index] = replace(cell, phase="running")
                started.append(cell.key)
                available -= 1
        if not started:
            return _seal_if_complete(_event(state, "no planned cells available"))
        state = replace(
            state,
            cells=tuple(cells),
            scheduler="running",
            run_state="unsealed",
        )
        return _event(state, "started: " + ", ".join(started))
    if action.kind == "complete":
        return _seal_if_complete(
            _terminalize_first_running(state, "valid_completed", "verifier-completed")
        )
    if action.kind == "harness":
        return _seal_if_complete(
            _terminalize_first_running(
                state, "valid_harness_outcome", "harness-or-submission-outcome"
            )
        )
    if action.kind == "limit":
        return _seal_if_complete(
            _terminalize_first_running(state, "valid_limit_outcome", "declared-limit")
        )
    if action.kind == "infrastructure":
        return _global_abort(
            state, "invalid_infrastructure", "shared-infrastructure-failure"
        )
    if action.kind == "integrity":
        return _global_abort(state, "invalid_integrity", "protected-boundary-event")
    if action.kind == "operator_abort":
        cells = [
            replace(
                cell,
                phase="terminal",
                disposition="aborted_operator",
                reason="operator-stop",
            )
            if cell.phase == "running"
            else cell
            for cell in state.cells
        ]
        return _event(
            replace(
                state,
                cells=tuple(cells),
                scheduler="operator-stopped",
                run_state="incomplete",
                validity="invalid",
            ),
            "operator stopped active cells; untouched cells remain resumable",
        )
    if action.kind == "crash":
        cells = [
            replace(cell, phase="interrupted") if cell.phase == "running" else cell
            for cell in state.cells
        ]
        return _event(
            replace(
                state,
                cells=tuple(cells),
                scheduler="crashed",
                run_state="unsealed",
                validity="unknown",
            ),
            "coordinator crashed; start records remain",
        )
    if action.kind == "resume":
        if state.scheduler == "operator-stopped":
            return _event(
                replace(state, scheduler="ready"),
                "resume accepted: only untouched cells are schedulable",
            )
        if state.scheduler == "crashed":
            return _global_abort(
                state,
                "invalid_infrastructure",
                "started-cell-missing-terminal-record",
            )
        if state.scheduler == "sealed":
            return _event(state, "sealed run: resume is inspect/no-op")
        return _event(state, "resume rejected: run is not resumable")
    return _event(state, f"unknown action: {action.kind}")
