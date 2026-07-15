"""PROTOTYPE — discard after the Functional V1 envelope decision.

Question: does one fixed three-slot native Linux/amd64 envelope, with only token
and cost thresholds configurable inside strict caps, give Functional V1 enough
capacity admission and failure behavior without becoming a general scheduler?

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

MINIMUM_CPU_CORES = 8
MINIMUM_MEMORY_MIB = 24_576
MINIMUM_FREE_DISK_MIB = 51_200
GLOBAL_CPU_RESERVE = 2
GLOBAL_MEMORY_RESERVE_MIB = 2_048
GLOBAL_DISK_RESERVE_MIB = 10_240
PER_SLOT_MEMORY_OVERHEAD_MIB = 1_024
PER_SLOT_DISK_OVERHEAD_MIB = 1_024
TOKEN_THRESHOLD_CAP = 500_000
COST_THRESHOLD_CAP_USD = Decimal("20.00")


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


V1_TEMPLATE = Envelope(
    max_parallel=3,
    cpu_cores_per_trial=2,
    memory_mib_per_trial=4_096,
    writable_disk_mib_per_trial=8_192,
    wall_time_seconds_per_trial=1_800,
    requests_per_trial=64,
    provider_tokens_per_trial=100_000,
    stop_after_cost_usd_per_trial=Decimal("5.00"),
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
    envelope: Envelope = V1_TEMPLATE
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


def preflight(host: HostProfile, envelope: Envelope) -> PreflightReport:
    failures: list[str] = []
    warnings: list[str] = []

    fixed_fields = (
        "max_parallel",
        "cpu_cores_per_trial",
        "memory_mib_per_trial",
        "writable_disk_mib_per_trial",
        "wall_time_seconds_per_trial",
        "requests_per_trial",
    )
    for name in fixed_fields:
        actual = getattr(envelope, name)
        expected = getattr(V1_TEMPLATE, name)
        if actual != expected:
            failures.append(f"{name} must equal fixed V1 value {expected}, got {actual}")

    if not 1 <= envelope.provider_tokens_per_trial <= TOKEN_THRESHOLD_CAP:
        failures.append(
            "provider_tokens_per_trial must be between 1 and "
            f"{TOKEN_THRESHOLD_CAP}"
        )
    if not Decimal("0.01") <= envelope.stop_after_cost_usd_per_trial <= COST_THRESHOLD_CAP_USD:
        failures.append(
            "stop_after_cost_usd_per_trial must be between $0.01 and "
            f"${COST_THRESHOLD_CAP_USD}"
        )

    if host.container_platform != "linux/amd64":
        failures.append(
            f"Functional V1 requires linux/amd64, got {host.container_platform}"
        )
    if host.cpu_cores < MINIMUM_CPU_CORES:
        failures.append(
            f"worker requires at least {MINIMUM_CPU_CORES} CPU, got {host.cpu_cores}"
        )
    if host.memory_mib < MINIMUM_MEMORY_MIB:
        failures.append(
            f"worker requires at least {MINIMUM_MEMORY_MIB} MiB RAM, got {host.memory_mib}"
        )
    if host.writable_disk_free_mib < MINIMUM_FREE_DISK_MIB:
        failures.append(
            "worker requires at least "
            f"{MINIMUM_FREE_DISK_MIB} MiB free Docker storage, "
            f"got {host.writable_disk_free_mib}"
        )
    if not host.hard_storage_quota:
        failures.append("Docker overlay2/XFS pquota enforcement probe failed")
    if not host.qualified_egress_backend:
        failures.append("native Linux guarded-public-web enforcement probe failed")

    capacity = capacity_for(host, envelope)
    if capacity.safe_parallel < V1_TEMPLATE.max_parallel:
        failures.append(
            f"fixed max_parallel={V1_TEMPLATE.max_parallel} exceeds safe capacity "
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


def _cycle_tokens(value: int) -> int:
    values = (100_000, 250_000, 500_000)
    return values[(values.index(value) + 1) % len(values)] if value in values else values[0]


def _cycle_cost(value: Decimal) -> Decimal:
    values = (Decimal("5.00"), Decimal("10.00"), Decimal("20.00"))
    return values[(values.index(value) + 1) % len(values)] if value in values else values[0]


def reduce(state: PrototypeState, action: Action) -> PrototypeState:
    if action.kind == "reset":
        return PrototypeState(host=state.host)
    if action.kind == "select_host" and action.host is not None:
        return PrototypeState(host=action.host)
    if action.kind == "template":
        return _event(
            replace(state, envelope=V1_TEMPLATE, preflight=None),
            "loaded V1 template envelope",
        )
    if action.kind == "tokens":
        value = _cycle_tokens(state.envelope.provider_tokens_per_trial)
        envelope = replace(state.envelope, provider_tokens_per_trial=value)
        return _event(
            replace(state, envelope=envelope, preflight=None),
            f"set provider_tokens_per_trial={value}",
        )
    if action.kind == "cost":
        value = _cycle_cost(state.envelope.stop_after_cost_usd_per_trial)
        envelope = replace(state.envelope, stop_after_cost_usd_per_trial=value)
        return _event(
            replace(state, envelope=envelope, preflight=None),
            f"set stop_after_cost_usd_per_trial=${value}",
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
