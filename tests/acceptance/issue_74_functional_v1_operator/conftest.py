from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.functional_v1 import CONDITIONS, SCENARIOS
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry


_HEX = "0" * 64


def _pricing_record() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 3,
        "billing_basis": "opencode-go-catalog",
        "currency": "USD",
        "unit": "usd-per-million-tokens",
        "input_usd_per_million_tokens": "1.00",
        "output_usd_per_million_tokens": "2.00",
        "cache_read_usd_per_million_tokens": "0.10",
        "tiers": [],
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "effective_until_utc": "2027-01-01T00:00:00Z",
        "source_url": "https://provider.example/pricing",
        "source_snapshot_sha256": f"sha256:{_HEX}",
        "retrieved_at_utc": "2026-01-01T00:00:00Z",
    }
    value["identity"] = str(
        TypedDigest.from_bytes(DigestKind.PRICING_RECORD, canonical_json_bytes(value))
    )
    return value


def _scenario_lock(name: str) -> bytes:
    registry = SchemaRegistry(schema_root_path())
    value = {
        "harbor": {
            "commit": "527d50deb63a5d279e8c20593c18a2cbc7f61f9e",
            "task_content_sha256": f"harbor-task:sha256:{_HEX}",
        },
        "identities": {
            "scenario": {
                "digest": f"scenario:sha256:{_HEX}",
                "kind": "scenario",
                "version": "1.0.0",
            },
            "score_contract": {
                "digest": f"score-contract:sha256:{_HEX}",
                "kind": "score-contract",
                "version": "1.0.0",
            },
            "verifier": {
                "digest": f"verifier:sha256:{_HEX}",
                "kind": "verifier",
                "version": "1.0.0",
            },
        },
        "package": {
            "files": [
                {
                    "agent_visible": index < 3,
                    "bytes": index,
                    "mode": "0644",
                    "path": f"file-{index}.txt",
                    "role": "agent-resource" if index < 3 else "verifier-resource",
                    "sha256": f"artifact:sha256:{index:064x}",
                }
                for index in range(6)
            ],
            "payload_sha256": f"package-payload:sha256:{_HEX}",
        },
        "resolved_inputs": {
            "datasets": [],
            "images": [
                {
                    "identity": f"oci-image:sha256:{_HEX}",
                    "reference": f"example.invalid/{name}@sha256:{_HEX}",
                }
            ],
            "pristine": {
                "archive": None,
                "archive_sha256": None,
                "commit": "0" * 40,
                "license": "MIT",
                "origin": f"https://example.invalid/{name}.git",
                "tree_sha256": f"source-tree:sha256:{_HEX}",
            },
            "scenario_baseline": f"source-tree:sha256:{_HEX}",
            "seed_inputs": [],
        },
        "scenario_id": f"functional-v1/{name}",
        "schema": registry.envelope("model-benchmark/scenario-lock", 1),
        "standard_v1": {
            "id": "standard-v1",
            "sha256": f"execution-profile:sha256:{_HEX}",
        },
    }
    return canonical_json_bytes(value)


def _condition_lock(name: str) -> bytes:
    value = {
        "adapter": {
            "argv": [name, "run"],
            "configuration": {"mode": "stock"},
            "environment_names": ["MODEL_BENCHMARK_PROXY_TOKEN"],
            "harbor_agent": "model_benchmark.runtime.adapters.functional_v1:FunctionalV1ConditionAgent",
            "non_interactive": True,
            "self_update": False,
            "working_directory": "/workspace",
        },
        "artifact": {
            "digest": f"artifact:sha256:{_HEX}",
            "kind": "raw-api-materializer"
            if name == "raw-api"
            else "native-executable",
            "platform": "linux/amd64",
        },
        "condition": name,
        "evidence": {"required_paths": ["stderr.txt", "stdout.txt"]},
        "execution_profile": f"execution-profile:sha256:{_HEX}",
        "image": {
            "content_digest": f"artifact:sha256:{_HEX}",
            "kind": "condition-artifact-image",
            "mount_path": "/opt/model-benchmark-condition",
            "platform": "linux/amd64",
            "read_only": True,
        },
        "provider_mapping": {
            "base_url": "manifest-provider-base-url",
            "credential": "opaque-trial-proxy-token",
            "model": "manifest-provider-model",
        },
        "schema_version": 1,
    }
    return canonical_json_bytes(value)


def _manifest_value(root: Path) -> dict[str, Any]:
    locks = root / "locks"
    locks.mkdir()
    scenarios: dict[str, object] = {}
    for name in SCENARIOS:
        data = _scenario_lock(name)
        path = locks / f"{name}.lock.json"
        path.write_bytes(data)
        scenarios[name] = {
            "path": f"locks/{path.name}",
            "digest": str(TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, data)),
        }
    conditions: dict[str, object] = {}
    for name in CONDITIONS:
        data = _condition_lock(name)
        path = locks / f"{name}.condition.json"
        path.write_bytes(data)
        conditions[name] = {
            "path": f"locks/{path.name}",
            "digest": str(
                TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data)
            ),
        }
    return {
        "schema_version": 1,
        "provider": {
            "base_url": "https://provider.example/v1",
            "model": "exact/model-slug",
            "protocol": "openai-chat-completions",
            "pricing": _pricing_record(),
        },
        "limits": {
            "requests_per_trial": 64,
            "provider_tokens_per_trial": 100_000,
            "stop_after_cost_usd_per_trial": "5.00",
            "wall_time_seconds_per_trial": 1_800,
            "cpu_cores_per_trial": 2,
            "memory_mib_per_trial": 4_096,
            "writable_disk_mib_per_trial": 8_192,
        },
        "execution": {
            "max_parallel": 3,
            "network_policy": "proxy-only-v1",
        },
        "scenarios": scenarios,
        "conditions": conditions,
    }


@pytest.fixture
def manifest_bundle(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    value = _manifest_value(tmp_path)
    path = tmp_path / "functional-v1.yaml"
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path, deepcopy(value)
