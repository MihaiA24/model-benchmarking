from __future__ import annotations

import urllib.error
import urllib.request

from pathlib import Path

import pytest

import model_benchmark.runtime.dry_launch_qualification as qualification
from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.schemas import SchemaRegistry
from model_benchmark.declarations.scenario_locks import schema_root_path

_SCHEMA_REGISTRY = SchemaRegistry(schema_root_path())


_DIGEST = "0" * 64
_TIMESTAMP = "2026-07-22T12:00:00Z"
_MANIFESTS = (
    ("functional-v1-manifest.yaml", "deepseek-v4-flash"),
    ("functional-v1-mimo-v2.5.yaml", "mimo-v2.5"),
    ("functional-v1-minimax-m3.yaml", "minimax-m3"),
    ("functional-v1-hy3.yaml", "hy3"),
)
_SCENARIOS = (
    "python-sales-by-genre",
    "spring-petvalidator-whitespace",
    "angular-reading-time",
    "react-author-filter",
)
_CONDITIONS = ("omp", "opencode", "hermes", "raw-api")


def _record() -> dict[str, object]:
    cells = []
    for index, (scenario, condition) in enumerate(
        ((scenario, condition) for scenario in _SCENARIOS for condition in _CONDITIONS),
        start=1,
    ):
        cells.append(
            {
                "cell_id": f"{index:02d}-{scenario}-{condition}",
                "condition": condition,
                "disposition": "valid_completed",
                "evidence_valid": True,
                "lifecycle": {
                    "bundle_sealed": True,
                    "cleanup_complete": True,
                    "condition_exited": True,
                    "condition_started": True,
                    "proxy_request_observed": True,
                    "trusted_submission_capture": True,
                    "verifier_completed": True,
                },
                "provider_requests": 1,
                "provider_tokens": 2,
                "reason_code": "completed",
                "result_bundle_identity": f"result-bundle:sha256:{index:064x}",
                "scenario": scenario,
                "terminal_phase": "verification",
            }
        )
    manifests = [
        {
            "base_url": "https://opencode.ai/zen/go/v1",
            "catalog_cache_read_usd_per_million_tokens": "0.0028",
            "catalog_context_tokens": 1_000_000,
            "catalog_input_usd_per_million_tokens": "0.14",
            "catalog_output_usd_per_million_tokens": "0.28",
            "catalog_output_tokens": 131_072,
            "catalog_tiers": [],
            "effective_from_utc": _TIMESTAMP,
            "effective_until_utc": "2026-09-01T00:00:00Z",
            "live_route_status": 401,
            "manifest": manifest,
            "manifest_identity": f"functional-v1-manifest:sha256:{_DIGEST}",
            "model": model,
            "pricing_identity": f"pricing-record:sha256:{_DIGEST}",
            "pricing_source_snapshot_sha256": f"sha256:{_DIGEST}",
            "pricing_source_url": qualification._CATALOG_URL,
            "resolved_manifest_identity": f"resolved-v1-manifest:sha256:{_DIGEST}",
            "source_yaml_sha256": f"sha256:{_DIGEST}",
            "status": "passed",
        }
        for manifest, model in _MANIFESTS
    ]
    return {
        "catalog_validation": {
            "catalog_document_sha256": f"sha256:{_DIGEST}",
            "manifests": manifests,
            "provider_id": "opencode-go",
            "retrieved_at_utc": _TIMESTAMP,
            "schema_version": 2,
            "source_url": qualification._CATALOG_URL,
            "status": "passed",
        },
        "cells": cells,
        "execution": {
            "completed_at_utc": _TIMESTAMP,
            "manifest_identity": f"functional-v1-manifest:sha256:{_DIGEST}",
            "manifest_source_sha256": f"sha256:{_DIGEST}",
            "resolved_manifest_identity": f"resolved-v1-manifest:sha256:{_DIGEST}",
            "runtime_tree_digest": f"artifact:sha256:{_DIGEST}",
            "started_at_utc": _TIMESTAMP,
        },
        "local_provider": {
            "external_cost_usd": "0",
            "external_provider_requests": 0,
            "implementation_sha256": f"sha256:{_DIGEST}",
            "local_provider_requests": 16,
            "network": "loopback-only",
            "response_sha256": f"sha256:{_DIGEST}",
            "substitution": "loopback-deterministic-v1",
        },
        "network": {
            "after_execution": "down",
            "before_execution": "down",
            "external_egress_observed": 0,
            "proxy_network": "internal",
            "restored": "up",
            "worker_uplink": "mb-host0",
        },
        "schema": _SCHEMA_REGISTRY.envelope(
            "model-benchmark/functional-v1-dry-launch-qualification", 2
        ),
        "schema_version": 2,
        "sealed_at_utc": _TIMESTAMP,
        "summary": {
            "cleanup_complete": True,
            "invalid_infrastructure": 0,
            "invalid_integrity": 0,
            "run_record_created": False,
            "sealed_bundles": 16,
            "task_success_required": False,
            "terminal_lifecycles": 16,
        },
    }


def test_catalog_validation_rejects_model_protocol_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeManifest:
        source_path = Path("functional-v1-minimax-m3.yaml")
        identity = f"functional-v1-manifest:sha256:{_DIGEST}"
        resolved_identity = f"resolved-v1-manifest:sha256:{_DIGEST}"
        source_yaml_sha256 = f"sha256:{_DIGEST}"
        value = {
            "provider": {
                "base_url": "https://opencode.ai/zen/go/v1",
                "model": "minimax-m3",
                "protocol": "openai-chat-completions",
                "pricing": {
                    "effective_from_utc": _TIMESTAMP,
                    "effective_until_utc": "2026-09-01T00:00:00Z",
                    "identity": f"pricing-record:sha256:{_DIGEST}",
                    "input_usd_per_million_tokens": "0.30",
                    "output_usd_per_million_tokens": "1.20",
                },
            }
        }

    catalog_provider = {
        "api": "https://opencode.ai/zen/go/v1",
        "npm": "@ai-sdk/openai-compatible",
        "models": {
            "minimax-m3": {
                "cost": {"input": 0.3, "output": 1.2},
                "id": "minimax-m3",
                "provider": {"npm": "@ai-sdk/anthropic"},
            }
        },
    }
    monkeypatch.setattr(qualification, "_check_pricing_window", lambda *_: None)

    with pytest.raises(
        qualification.DryLaunchQualificationError, match="protocol drift"
    ):
        qualification._manifest_catalog_entry(
            FakeManifest(),  # type: ignore[arg-type]
            catalog_document_sha256=f"sha256:{_DIGEST}",
            provider=catalog_provider,
            route_status=401,
        )


def test_catalog_limits_require_positive_integer_context_and_output() -> None:
    assert qualification._catalog_limits(
        {"limit": {"context": 1_000_000, "output": 131_072}},
        "minimax-m3",
    ) == (1_000_000, 131_072)

    with pytest.raises(
        qualification.DryLaunchQualificationError, match="limits are invalid"
    ):
        qualification._catalog_limits(
            {"limit": {"context": 1_000_000, "output": True}},
            "minimax-m3",
        )


def test_dry_launch_record_schema_requires_complete_non_run_lifecycle() -> None:
    record = _record()
    validated = _SCHEMA_REGISTRY.validate_bytes(canonical_json_bytes(record))
    assert validated == record
    qualification._validate_record(record)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("network", "external_egress_observed"), 1),
        (("summary", "run_record_created"), True),
        (("summary", "sealed_bundles"), 15),
        (("cells", 0, "disposition"), "invalid_infrastructure"),
        (("cells", 0, "provider_requests"), 0),
    ),
)
def test_dry_launch_record_rejects_invalid_lifecycle(
    path: tuple[str | int, ...], value: object
) -> None:
    record = _record()
    target: object = record
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(qualification.DryLaunchQualificationError):
        qualification._validate_record(record)


def test_seal_writes_identity_and_inventory_only_after_uplink_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _record()
    draft.pop("sealed_at_utc")
    draft_path = tmp_path / "draft.json"
    draft_path.write_bytes(canonical_json_bytes(draft))
    output = tmp_path / "dry-launch-qualification.json"
    monkeypatch.setattr(qualification, "_link_state", lambda _name: "up")

    identity = qualification.seal_qualification(
        draft_path, output=output, worker_uplink="mb-host0"
    )

    assert str(identity).startswith("dry-launch-qualification:sha256:")
    assert output.is_file()
    assert output.with_suffix(".identity").read_text(encoding="utf-8").strip() == str(
        identity
    )
    inventory = output.with_suffix(".sha256").read_text(encoding="utf-8")
    assert output.name in inventory
    assert output.with_suffix(".identity").name in inventory
    inspected = qualification.inspect_qualification(output)
    assert inspected["terminal_lifecycles"] == 16
    assert inspected["sealed_bundles"] == 16


def test_execute_preflights_without_reading_provider_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BoundaryReached(RuntimeError):
        pass

    class FakeManifest:
        identity = "functional-v1-manifest:sha256:" + _DIGEST
        value = {"provider": {"model": "deepseek-v4-flash"}}

    class FakeManifestLoader:
        @staticmethod
        def load(_path: Path) -> FakeManifest:
            return FakeManifest()

    class FakeLease:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: object) -> None:
            return None

    class FakeHome:
        def __init__(self, _path: Path) -> None:
            pass

        def coordinator_lease(self) -> FakeLease:
            return FakeLease()

    class FakeRuntime:
        def __init__(self, _home: FakeHome) -> None:
            pass

        def _preflight(
            self,
            _manifest: FakeManifest,
            *,
            require_provider_credential: bool = True,
        ) -> None:
            assert require_provider_credential is False
            raise BoundaryReached

    monkeypatch.delenv("MODEL_BENCHMARK_PROVIDER_API_KEY", raising=False)
    monkeypatch.setattr(qualification, "FunctionalV1Manifest", FakeManifestLoader)
    monkeypatch.setattr(qualification, "FunctionalV1Home", FakeHome)
    monkeypatch.setattr(qualification, "NativeFunctionalV1Runtime", FakeRuntime)
    monkeypatch.setattr(qualification, "_load_catalog_validation", lambda *_: {})
    monkeypatch.setattr(qualification, "_check_pricing_window", lambda *_: None)
    monkeypatch.setattr(qualification, "_link_state", lambda *_: "down")

    with pytest.raises(BoundaryReached):
        qualification.execute_qualification(
            tmp_path / "reference.yaml",
            [tmp_path / f"manifest-{index}.yaml" for index in range(4)],
            home_path=tmp_path / "home",
            catalog_validation_path=tmp_path / "catalog.json",
            draft_path=tmp_path / "draft.json",
            worker_uplink="mb-host0",
        )


@pytest.mark.parametrize(
    ("protocol", "endpoint", "anthropic_version"),
    [
        ("openai-chat-completions", "/chat/completions", None),
        ("anthropic-messages", "/messages", "2023-06-01"),
    ],
)
def test_live_route_probe_is_endpoint_specific_and_credential_free(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    endpoint: str,
    anthropic_version: str | None,
) -> None:
    observed: list[bool] = []

    def reject(request: urllib.request.Request, *, timeout: int) -> None:
        assert request.full_url.endswith(endpoint)
        assert request.get_method() == "POST"
        assert request.data == b"{}"
        assert request.get_header("Authorization") is None
        assert request.get_header("X-api-key") is None
        assert request.get_header("Anthropic-version") == anthropic_version
        assert timeout == 20
        observed.append(True)
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(qualification.urllib.request, "urlopen", reject)

    assert (
        qualification._live_route_status("https://opencode.ai/zen/go/v1", protocol)
        == 401
    )
    assert observed == [True]


def test_catalog_validation_rejects_missing_protocol_route() -> None:
    manifest = qualification.FunctionalV1Manifest.load(
        Path(__file__).resolve().parents[2] / "functional-v1-minimax-m3.yaml"
    )
    provider_value = manifest.value["provider"]
    pricing = provider_value["pricing"]
    tier = pricing["tiers"][0]
    catalog_provider = {
        "api": provider_value["base_url"],
        "models": {
            provider_value["model"]: {
                "cost": {
                    "cache_read": pricing["cache_read_usd_per_million_tokens"],
                    "input": pricing["input_usd_per_million_tokens"],
                    "output": pricing["output_usd_per_million_tokens"],
                    "tiers": [
                        {
                            "cache_read": tier["cache_read_usd_per_million_tokens"],
                            "input": tier["input_usd_per_million_tokens"],
                            "output": tier["output_usd_per_million_tokens"],
                            "tier": {
                                "size": tier["input_tokens_gt"],
                                "type": "context",
                            },
                        }
                    ],
                },
                "id": provider_value["model"],
                "limit": {"context": 1_000_000, "output": 131_072},
                "provider": {"npm": "@ai-sdk/anthropic"},
            }
        },
    }

    with pytest.raises(
        qualification.DryLaunchQualificationError,
        match="did not reject an unauthenticated probe",
    ):
        qualification._manifest_catalog_entry(
            manifest,
            catalog_document_sha256=pricing["source_snapshot_sha256"],
            provider=catalog_provider,
            route_status=404,
        )
