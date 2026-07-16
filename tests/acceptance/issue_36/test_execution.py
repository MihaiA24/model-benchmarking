from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import tomllib
from collections import Counter
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest
import yaml

import model_benchmark.runtime.execution as execution
from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.adapters.functional_v1 import FunctionalV1ConditionAgent
from model_benchmark.runtime.execution import (
    INTERNAL_QUALIFICATION_STAGES,
    CellExecution,
    ExecutionError,
    FunctionalV1Coordinator,
    HarborCellExecutor,
    condition_image_content_digest,
)
from model_benchmark.runtime.functional_v1 import CELL_SCHEDULE


class _Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.run_id = "0198ae70-0000-7000-8000-000000000036"
        self.starts: list[str] = []
        self.executions: list[str] = []
        self._lock = threading.Lock()

    def write_cell_start(self, cell_id: str, **_: object) -> None:
        with self._lock:
            assert cell_id not in self.starts
            self.starts.append(cell_id)

    def write_cell_execution(self, cell_id: str, **_: object) -> None:
        with self._lock:
            assert cell_id not in self.executions
            self.executions.append(cell_id)


class _BlockingExecutor:
    def __init__(self) -> None:
        self.gates = [threading.Event() for _ in CELL_SCHEDULE]
        self.started = [threading.Event() for _ in CELL_SCHEDULE]
        self.calls: list[int] = []
        self.active = 0
        self.maximum_active = 0
        self.terminated = 0
        self._lock = threading.Lock()

    def run_cell(
        self,
        cell: dict[str, object],
        *,
        run_id: str,
        raw_root: Path,
        cancel: threading.Event,
    ) -> CellExecution:
        index = int(cell["index"])
        position = index - 1
        with self._lock:
            self.calls.append(index)
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        self.started[position].set()
        assert self.gates[position].wait(10)
        with self._lock:
            self.active -= 1
        return CellExecution(
            "valid_completed",
            "verification",
            "verifier-completed",
            index + 1,
            True,
            MappingProxyType({"index": index}),
        )

    def terminate_all(self) -> None:
        self.terminated += 1
        for gate in self.gates:
            gate.set()


class _FaultExecutor(_BlockingExecutor):
    def run_cell(
        self,
        cell: dict[str, object],
        *,
        run_id: str,
        raw_root: Path,
        cancel: threading.Event,
    ) -> CellExecution:
        index = int(cell["index"])
        position = index - 1
        with self._lock:
            self.calls.append(index)
        self.started[position].set()
        if index == 1:
            return CellExecution(
                "invalid_infrastructure",
                "provider",
                "provider-connection-failed",
                1,
                False,
                MappingProxyType({}),
            )
        assert self.gates[position].wait(10)
        return CellExecution(
            "invalid_infrastructure",
            "cleanup",
            "shared-fault-terminated",
            2,
            False,
            MappingProxyType({}),
        )


def test_scheduler_starts_exactly_three_and_refills_in_fixed_order(
    tmp_path: Path,
    acceptance_observation: Any,
) -> None:
    workspace = _Workspace(tmp_path)
    executor = _BlockingExecutor()
    coordinator = FunctionalV1Coordinator(workspace, executor)  # type: ignore[arg-type]
    result: list[tuple[CellExecution, ...]] = []
    thread = threading.Thread(target=lambda: result.append(coordinator.execute()))
    thread.start()

    assert all(event.wait(10) for event in executor.started[:3])
    assert not executor.started[3].is_set()
    executor.gates[0].set()
    assert executor.started[3].wait(10)
    assert not executor.started[4].is_set()
    for gate in executor.gates:
        gate.set()
    thread.join(10)

    assert not thread.is_alive()
    assert executor.maximum_active == 3
    assert executor.calls == list(range(1, 13))
    assert Counter(workspace.starts) == Counter(
        str(cell["cell_id"]) for cell in CELL_SCHEDULE
    )
    assert Counter(workspace.executions) == Counter(workspace.starts)
    assert len(result) == 1 and len(result[0]) == 12
    acceptance_observation(
        "fixed-three-slot-schedule",
        {
            "execution_order": executor.calls,
            "maximum_active": executor.maximum_active,
            "starts_per_cell": dict(Counter(workspace.starts)),
        },
    )


def test_shared_fault_stops_refill_and_terminates_running_cells(
    tmp_path: Path,
    acceptance_observation: Any,
) -> None:
    workspace = _Workspace(tmp_path)
    executor = _FaultExecutor()
    outcomes = FunctionalV1Coordinator(workspace, executor).execute()  # type: ignore[arg-type]

    assert sorted(executor.calls) == [1, 2, 3]
    assert executor.terminated == 1
    assert len(outcomes) == 3
    assert all(outcome.disposition == "invalid_infrastructure" for outcome in outcomes)
    acceptance_observation(
        "shared-fault-stops-refill",
        {"started_indices": sorted(executor.calls), "terminate_calls": executor.terminated},
    )


def test_four_condition_locks_pin_exact_read_only_image_payloads(
    acceptance_observation: Any,
) -> None:
    root = Path(__file__).resolve().parents[3]
    runtime_root = root / "src/model_benchmark"
    paths = {
        "omp": root / "profiles/functional-v1/omp-v16.4.0.condition.json",
        "opencode": root / "profiles/functional-v1/opencode-v1.17.18.condition.json",
        "hermes": root / "profiles/functional-v1/hermes-v0.18.2.condition.json",
        "raw-api": root / "profiles/functional-v1/raw-api-v1.condition.json",
    }
    identities: set[str] = set()
    observations: dict[str, object] = {}
    for condition, path in paths.items():
        data = path.read_bytes()
        lock = json.loads(data)
        assert canonical_json_bytes(lock) == data
        assert lock["condition"] == condition
        assert lock["adapter"]["argv"][0] == (
            "/opt/model-benchmark-condition/entrypoint"
        )
        assert lock["adapter"]["harbor_agent"] == (
            "model_benchmark.runtime.adapters.functional_v1:FunctionalV1ConditionAgent"
        )
        assert lock["image"] == {
            "content_digest": condition_image_content_digest(
                condition, lock, runtime_root
            ),
            "kind": "condition-artifact-image",
            "mount_path": "/opt/model-benchmark-condition",
            "platform": "linux/amd64",
            "read_only": True,
        }
        identity = str(TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data))
        identities.add(identity)
        observations[condition] = {
            "condition_identity": identity,
            "image_content_digest": lock["image"]["content_digest"],
        }
    assert len(identities) == 4
    acceptance_observation("four-condition-image-locks", observations)


def test_runtime_package_binds_prebuilt_main_and_verifier_images(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    original = (
        'version = "1.0"\n\n[verifier]\nenvironment_mode = "separate"\n'
        '\n[environment]\ndocker_image = "harbor-agent@sha256:old"\n'
        'network_mode = "no-network"\n'
        '\n[verifier.environment]\n'
        'docker_image = "harbor-verifier@sha256:old"\n'
        'network_mode = "no-network"\n'
    )
    (source / "task.toml").write_text(original, encoding="utf-8")

    package, identity = execution._runtime_scenario_package(
        source,
        tmp_path / "runtime",
        main_image="model-benchmark.local/main:sealed",
        verifier_image="model-benchmark.local/verifier:sealed",
    )

    value = tomllib.loads((package / "task.toml").read_text(encoding="utf-8"))
    assert value["environment"]["docker_image"] == ("model-benchmark.local/main:sealed")
    assert value["verifier"]["environment"]["docker_image"] == (
        "model-benchmark.local/verifier:sealed"
    )
    assert value["verifier"]["environment"]["network_mode"] == "no-network"
    assert not ((package / "task.toml").stat().st_mode & 0o222)
    assert (source / "task.toml").read_text(encoding="utf-8") == original
    assert str(identity).startswith("artifact:sha256:")
    execution._remove_sealed_tree(package)
    assert not package.exists()


def test_limit_probe_uses_overlay2_size_storage_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_options: list[str] = []

    def fake_docker(
        arguments: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ["container", "create"]:
            option = arguments[arguments.index("--storage-opt") + 1]
            storage_options.append(option)
            assert option == "size=8192M"
            return subprocess.CompletedProcess(
                arguments, 0, stdout="limit-probe\n", stderr=""
            )
        if arguments[:2] == ["container", "inspect"]:
            host_config = {
                "NanoCpus": 2_000_000_000,
                "Memory": 4096 * 1024**2,
                "MemorySwap": 4096 * 1024**2,
                "PidsLimit": 256,
            }
            return subprocess.CompletedProcess(
                arguments, 0, stdout=json.dumps(host_config), stderr=""
            )
        if arguments[:1] == ["run"]:
            option = arguments[arguments.index("--storage-opt") + 1]
            storage_options.append(option)
            assert option == "size=8192M"
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(execution, "_docker", fake_docker)
    monkeypatch.setattr(
        execution, "_probe_wall_time_enforcement", lambda *_: {"passed": True}
    )

    result = execution._probe_limits("coordinator:sealed", "run-id")

    assert storage_options == ["size=8192M", "size=8192M"]
    assert result["storage_mib"] == 8192


def test_network_probe_launches_harbor_firewall_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    cleaned: list[str] = []

    def fake_docker(
        arguments: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[:2] == ["container", "inspect"]:
            networks = {"mb-run-id-internal": {"IPAddress": "172.30.0.2"}}
            return subprocess.CompletedProcess(
                arguments, 0, stdout=json.dumps(networks), stderr=""
            )
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(execution, "_docker", fake_docker)
    monkeypatch.setattr(execution, "_cleanup_owned", cleaned.append)

    result = execution._probe_network(
        "proxy:sealed", "coordinator:sealed", "egress:sealed", "run-id"
    )

    firewall = next(arguments for arguments in calls if "egress:sealed" in arguments)
    assert "--entrypoint" in firewall
    assert firewall[firewall.index("--entrypoint") + 1] == (
        "/opt/egress-sidecar/entrypoint.sh"
    )
    assert [
        "exec",
        "mb-run-id-firewall",
        "network-policy",
        "allow",
        "172.30.0.2",
    ] in calls
    main_probe = next(
        arguments for arguments in calls if "coordinator:sealed" in arguments
    )
    assert "172.30.0.2" in main_probe[-1]
    assert "mb-proxy" not in main_probe[-1]
    assert result["direct_egress_denied"] is True
    assert cleaned == ["run-id"]


def test_condition_mount_probe_allows_coordinator_runtime_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_docker(
        arguments: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[-2:] == ["ls", "/opt"]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout="model-benchmark-condition\nmodel-benchmark-runtime\n",
                stderr="",
            )
        returncode = 1 if arguments[-2:] == ["-e", "/opt/model-benchmark-condition/verifier"] else 0
        return subprocess.CompletedProcess(
            arguments, returncode, stdout="", stderr=""
        )

    conditions = {
        condition: {"image_id": f"oci-image:sha256:{condition}", "reference": f"condition:{condition}"}
        for condition in execution.CONDITIONS
    }
    inventory = execution.ProvisioningInventory(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, b"inventory"),
        {"conditions": conditions},
        tmp_path / "inventory.json",
    )
    monkeypatch.setattr(execution, "_docker", fake_docker)

    results = execution._probe_condition_mounts(
        inventory, "coordinator:sealed", "run-id"
    )

    assert len(results) == 4
    assert all(result["unselected_artifacts_present"] is False for result in results)


def test_provider_limit_and_score_vector_are_terminal_facts(tmp_path: Path) -> None:
    executor = HarborCellExecutor.__new__(HarborCellExecutor)
    result_path = tmp_path / "trial" / "result.json"
    verifier = result_path.parent / "verifier"
    verifier.mkdir(parents=True)
    (verifier / "verifier-result.json").write_text(
        json.dumps(
            {
                "domain_scores": {"behavior": 1},
                "acceptance_score": 1,
                "regression_score": 1,
                "task_success": True,
            }
        ),
        encoding="utf-8",
    )
    events = [
        {
            "event": "provider-response",
            "provider_tokens": 101,
            "provider_cost_usd": "0.51",
            "budget_events": ["tokens-stop-after-response"],
            "token_overshoot": 1,
            "cost_overshoot_usd": "0.01",
        }
    ]

    outcome = executor._execution(
        result_path, {"agent_result": {"metadata": {"exit_code": 0}}}, events, 99
    )

    assert outcome.disposition == "valid_limit_outcome"
    assert outcome.reason_code == "tokens-stop-after-response"
    assert outcome.details["provider_tokens"] == 101
    assert outcome.details["token_overshoot"] == 1
    assert outcome.details["cost_overshoot_usd"] == "0.01"
    assert outcome.details["score_vector"] == {
        "acceptance_score": 1,
        "behavior": 1,
        "regression_score": 1,
        "task_success": True,
    }


def test_missing_provider_usage_or_cost_is_invalid_infrastructure(
    tmp_path: Path,
) -> None:
    executor = HarborCellExecutor.__new__(HarborCellExecutor)
    result_path = tmp_path / "trial" / "result.json"
    outcome = executor._execution(
        result_path,
        {"agent_result": {"metadata": {"exit_code": 0}}},
        [
            {
                "event": "provider-response",
                "provider_tokens": None,
                "provider_cost_usd": None,
                "budget_events": [],
            }
        ],
        100,
    )

    assert outcome.disposition == "invalid_infrastructure"
    assert outcome.reason_code == "provider-usage-or-cost-missing"
    assert outcome.evidence_valid is False


def test_proxy_evidence_allows_container_append_and_host_read(tmp_path: Path) -> None:
    evidence_root = tmp_path / "proxy-evidence"

    event_log = execution._prepare_proxy_evidence(evidence_root)

    assert evidence_root.stat().st_mode & 0o777 == 0o733
    assert event_log.stat().st_mode & 0o777 == 0o622
    event_log.write_text("event\n", encoding="utf-8")
    assert event_log.read_text(encoding="utf-8") == "event\n"


def test_harbor_overlay_exposes_only_selected_image_and_proxy_route(
    tmp_path: Path,
    acceptance_observation: Any,
) -> None:
    executor = HarborCellExecutor.__new__(HarborCellExecutor)
    overlay = tmp_path / "overlay.yaml"
    executor._overlay(
        overlay,
        run_id="0198ae70-0000-7000-8000-000000000036",
        cell_id="python-sales-by-genre--omp",
        condition_image="model-benchmark.local/functional-v1/omp:locked",
        main_image="model-benchmark.local/scenario-main:locked",
        capture_image="model-benchmark.local/scenario-capture:locked",
        proxy_image="model-benchmark.local/functional-v1/credential-proxy:locked",
        proxy_evidence=tmp_path / "proxy-evidence",
    )
    value = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    main = value["services"]["main"]
    proxy = value["services"]["credential-proxy"]

    assert main["image"] == "model-benchmark.local/scenario-main:locked"
    assert main["pull_policy"] == "never"
    assert main["storage_opt"] == {"size": "8192M"}
    capture = value["services"]["capture"]
    assert "build" not in capture
    assert capture["image"] == "model-benchmark.local/scenario-capture:locked"
    assert capture["pull_policy"] == "never"
    assert "networks" not in main
    assert value["services"][execution._HARBOR_EGRESS_SERVICE]["networks"] == [
        "proxy-only"
    ]
    assert main["volumes"] == [
        {
            "read_only": True,
            "source": "model-benchmark.local/functional-v1/omp:locked",
            "target": "/opt/model-benchmark-condition",
            "type": "image",
        }
    ]
    assert execution._condition_mounts(
        "model-benchmark.local/functional-v1/hermes:locked"
    ) == [
        {
            "read_only": True,
            "source": "model-benchmark.local/functional-v1/hermes:locked",
            "target": "/opt/model-benchmark-condition",
            "type": "image",
        }
    ]
    assert all("docker.sock" not in json.dumps(item) for item in main["volumes"])
    assert value["networks"]["proxy-only"]["internal"] is True
    assert proxy["networks"] == ["proxy-only", "provider-egress"]
    assert "MODEL_BENCHMARK_PROVIDER_API_KEY" not in main.get("environment", {})
    assert proxy["environment"]["MODEL_BENCHMARK_REQUESTS_PER_TRIAL"] == (
        "${MODEL_BENCHMARK_REQUESTS_PER_TRIAL:?}"
    )
    assert proxy["environment"]["MODEL_BENCHMARK_PROVIDER_API_KEY"] == (
        "${MODEL_BENCHMARK_PROVIDER_API_KEY:?}"
    )
    acceptance_observation(
        "selected-image-proxy-only-overlay",
        {
            "main_network": "service:harbor-docker-egress-control-sidecar",
            "main_volumes": main["volumes"],
            "proxy_networks": proxy["networks"],
        },
    )


def test_harbor_agent_command_has_only_proxy_credentials(tmp_path: Path) -> None:
    agent = FunctionalV1ConditionAgent(
        logs_dir=tmp_path,
        condition="omp",
        entrypoint="/opt/model-benchmark-condition/entrypoint",
        artifact_identity="artifact:sha256:" + "a" * 64,
        extra_env={
            "MODEL_BENCHMARK_PROVIDER_MODEL": "locked/model",
            "MODEL_BENCHMARK_PROXY_BASE_URL": "http://credential-proxy:8080/v1",
            "MODEL_BENCHMARK_PROXY_TOKEN": "opaque-token",
        },
    )
    command, environment = agent._command()

    assert command.split()[:3] == [
        "/opt/model-benchmark-condition/entrypoint",
        "--condition",
        "omp",
    ]
    assert set(environment) == {
        "HOME",
        "MODEL_BENCHMARK_PROVIDER_MODEL",
        "MODEL_BENCHMARK_PROXY_BASE_URL",
        "MODEL_BENCHMARK_PROXY_TOKEN",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
    assert "MODEL_BENCHMARK_PROVIDER_API_KEY" not in environment
    assert environment["HOME"] == "/logs/agent/home"


def test_harbor_agent_install_leaves_evidence_directory_fresh(tmp_path: Path) -> None:
    calls: list[tuple[str, str, int]] = []

    class Environment:
        async def exec(
            self, command: str, *, user: str, timeout_sec: int
        ) -> SimpleNamespace:
            calls.append((command, user, timeout_sec))
            return SimpleNamespace(return_code=0)

    agent = FunctionalV1ConditionAgent(
        logs_dir=tmp_path,
        condition="omp",
        entrypoint="/opt/model-benchmark-condition/entrypoint",
        artifact_identity="artifact:sha256:" + "a" * 64,
    )
    asyncio.run(agent.install(Environment()))

    assert calls[0][1:] == ("root", 30)
    assert calls[1] == ("mkdir -p /logs/agent/home", "65532", 30)
    assert all(".model-benchmark" not in command for command, _, _ in calls)


def test_native_preflight_rejects_before_docker_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(execution.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        execution,
        "_docker",
        lambda *args, **kwargs: pytest.fail("Docker must not run on unsupported host"),
    )

    with pytest.raises(ExecutionError) as captured:
        execution._native_host()

    assert captured.value.reason_code == "unsupported-native-platform"


def test_internal_qualification_stages_are_fixed_schedule_subsets() -> None:
    scenario = "python-sales-by-genre"
    stages = INTERNAL_QUALIFICATION_STAGES

    assert set(stages) == {
        "single-omp",
        "single-opencode",
        "single-hermes",
        "four-condition",
        "twelve-cell",
    }
    for condition in ("omp", "opencode", "hermes"):
        stage = stages[f"single-{condition}"]
        assert len(stage) == 1
        assert stage[0]["scenario"] == scenario
        assert stage[0]["condition"] == condition
    assert stages["four-condition"] == tuple(CELL_SCHEDULE[:4])
    assert all(cell["scenario"] == scenario for cell in stages["four-condition"])
    assert stages["twelve-cell"] == tuple(CELL_SCHEDULE)


def test_four_condition_qualification_refills_through_same_interface(
    tmp_path: Path,
    acceptance_observation: Any,
) -> None:
    workspace = _Workspace(tmp_path)
    executor = _BlockingExecutor()
    coordinator = FunctionalV1Coordinator(workspace, executor)  # type: ignore[arg-type]
    schedule = INTERNAL_QUALIFICATION_STAGES["four-condition"]
    result: list[tuple[CellExecution, ...]] = []
    thread = threading.Thread(
        target=lambda: result.append(coordinator.execute(schedule))
    )
    thread.start()

    assert all(event.wait(10) for event in executor.started[:3])
    assert not executor.started[3].is_set()
    executor.gates[0].set()
    assert executor.started[3].wait(10)
    for gate in executor.gates:
        gate.set()
    thread.join(10)

    assert not thread.is_alive()
    assert executor.maximum_active == 3
    assert executor.calls == [1, 2, 3, 4]
    assert len(result) == 1 and len(result[0]) == 4
    acceptance_observation(
        "four-condition-qualification-refill",
        {
            "execution_order": executor.calls,
            "maximum_active": executor.maximum_active,
        },
    )


def test_unknown_qualification_stage_is_rejected(tmp_path: Path) -> None:
    runtime = execution.NativeFunctionalV1Runtime.__new__(
        execution.NativeFunctionalV1Runtime
    )

    with pytest.raises(ExecutionError) as captured:
        runtime.internal_qualification(None, "partial-run")  # type: ignore[arg-type]

    assert captured.value.reason_code == "unknown-qualification-stage"


def test_drained_cell_raw_evidence_is_preserved_and_redacted(tmp_path: Path) -> None:
    executor = HarborCellExecutor.__new__(HarborCellExecutor)
    source = tmp_path / "cell"
    (source / "trials").mkdir(parents=True)
    (source / "trials" / "stdout.bin").write_bytes(b"before secret-value after")
    destination = tmp_path / "raw"

    preserved = executor._preserve_raw_evidence(
        source, destination, (b"secret-value",)
    )

    assert preserved is True
    assert (destination / "trials" / "stdout.bin").read_bytes() == (
        b"before [REDACTED] after"
    )


def test_drained_cell_evidence_with_symlink_is_dropped_not_leaked(
    tmp_path: Path,
) -> None:
    executor = HarborCellExecutor.__new__(HarborCellExecutor)
    source = tmp_path / "cell"
    source.mkdir()
    (source / "stdout.bin").write_bytes(b"data")
    (source / "escape").symlink_to(tmp_path)
    destination = tmp_path / "raw"

    preserved = executor._preserve_raw_evidence(source, destination, (b"token",))

    assert preserved is False
    assert not destination.exists()
