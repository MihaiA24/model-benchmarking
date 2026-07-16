from __future__ import annotations

import json
import threading
import tomllib
from collections import Counter
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

import model_benchmark.runtime.execution as execution
from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.execution import (
    CellExecution,
    ExecutionError,
    FunctionalV1Coordinator,
    HarborCellRunner,
    condition_image_content_digest,
)
from model_benchmark.runtime.functional_v1 import CELL_SCHEDULE
from model_benchmark.runtime.harbor_agent import FunctionalV1ConditionAgent


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


class _BlockingRunner:
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


class _FaultRunner(_BlockingRunner):
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
    runner = _BlockingRunner()
    coordinator = FunctionalV1Coordinator(workspace, runner)  # type: ignore[arg-type]
    result: list[tuple[CellExecution, ...]] = []
    thread = threading.Thread(target=lambda: result.append(coordinator.execute()))
    thread.start()

    assert all(event.wait(10) for event in runner.started[:3])
    assert not runner.started[3].is_set()
    runner.gates[0].set()
    assert runner.started[3].wait(10)
    assert not runner.started[4].is_set()
    for gate in runner.gates:
        gate.set()
    thread.join(10)

    assert not thread.is_alive()
    assert runner.maximum_active == 3
    assert runner.calls == list(range(1, 13))
    assert Counter(workspace.starts) == Counter(
        str(cell["cell_id"]) for cell in CELL_SCHEDULE
    )
    assert Counter(workspace.executions) == Counter(workspace.starts)
    assert len(result) == 1 and len(result[0]) == 12
    acceptance_observation(
        "fixed-three-slot-schedule",
        {
            "execution_order": runner.calls,
            "maximum_active": runner.maximum_active,
            "starts_per_cell": dict(Counter(workspace.starts)),
        },
    )


def test_shared_fault_stops_refill_and_terminates_running_cells(
    tmp_path: Path,
    acceptance_observation: Any,
) -> None:
    workspace = _Workspace(tmp_path)
    runner = _FaultRunner()
    outcomes = FunctionalV1Coordinator(workspace, runner).execute()  # type: ignore[arg-type]

    assert sorted(runner.calls) == [1, 2, 3]
    assert runner.terminated == 1
    assert len(outcomes) == 3
    assert all(outcome.disposition == "invalid_infrastructure" for outcome in outcomes)
    acceptance_observation(
        "shared-fault-stops-refill",
        {"started_indices": sorted(runner.calls), "terminate_calls": runner.terminated},
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
            "model_benchmark.runtime.harbor_agent:FunctionalV1ConditionAgent"
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
        '\n[environment]\nnetwork_mode = "no-network"\n'
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


def test_provider_limit_and_score_vector_are_terminal_facts(tmp_path: Path) -> None:
    runner = HarborCellRunner.__new__(HarborCellRunner)
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

    outcome = runner._execution(
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
    runner = HarborCellRunner.__new__(HarborCellRunner)
    result_path = tmp_path / "trial" / "result.json"
    outcome = runner._execution(
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


def test_harbor_overlay_exposes_only_selected_image_and_proxy_route(
    tmp_path: Path,
    acceptance_observation: Any,
) -> None:
    runner = HarborCellRunner.__new__(HarborCellRunner)
    overlay = tmp_path / "overlay.yaml"
    runner._overlay(
        overlay,
        run_id="0198ae70-0000-7000-8000-000000000036",
        cell_id="python-sales-by-genre--omp",
        condition="omp",
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
    capture = value["services"]["capture"]
    assert capture["build"] is None
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
        "hermes", "model-benchmark.local/functional-v1/hermes:locked"
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
