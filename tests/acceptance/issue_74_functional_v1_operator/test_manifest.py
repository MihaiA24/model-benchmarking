from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

import model_benchmark.runtime.execution as execution

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.functional_v1 import (
    CONDITIONS,
    SCENARIOS,
    FunctionalV1Manifest,
    FunctionalV1ManifestError,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def test_yaml_format_and_comments_change_only_source_digest(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, value = manifest_bundle
    first = FunctionalV1Manifest.load(path)
    reformatted = path.with_name("reformatted.yaml")
    reformatted.write_text(
        "# operator comment\n" + yaml.safe_dump(value, sort_keys=True),
        encoding="utf-8",
    )

    second = FunctionalV1Manifest.load(reformatted)

    assert second.identity == first.identity
    assert second.resolved_identity == first.resolved_identity
    assert second.source_yaml_sha256 != first.source_yaml_sha256


def test_changed_resolved_condition_changes_manifest_and_projection_identity(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, value = manifest_bundle
    first = FunctionalV1Manifest.load(path)
    condition_path = path.parent / value["conditions"]["omp"]["path"]
    condition = json.loads(condition_path.read_bytes())
    condition["adapter"]["configuration"] = {"mode": "stock", "version": "changed"}
    condition_bytes = canonical_json_bytes(condition)
    condition_path.write_bytes(condition_bytes)
    value["conditions"]["omp"]["digest"] = str(
        TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, condition_bytes)
    )
    changed_path = path.with_name("changed.yaml")
    _write_manifest(changed_path, value)

    changed = FunctionalV1Manifest.load(changed_path)

    assert changed.identity != first.identity
    assert changed.resolved_identity != first.resolved_identity


def test_manifest_fixes_matrix_and_execution_envelope(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, _ = manifest_bundle

    manifest = FunctionalV1Manifest.load(path)

    assert tuple(manifest.value["scenarios"]) == SCENARIOS
    assert tuple(manifest.value["conditions"]) == CONDITIONS
    assert manifest.value["execution"] == {
        "max_parallel": 3,
        "network_policy": "proxy-only-v1",
    }
    assert manifest.value["limits"] == {
        "cpu_cores_per_trial": 2,
        "memory_mib_per_trial": 4_096,
        "provider_tokens_per_trial": 100_000,
        "requests_per_trial": 64,
        "stop_after_cost_usd_per_trial": "5.00",
        "wall_time_seconds_per_trial": 1_800,
        "writable_disk_mib_per_trial": 8_192,
    }


def test_manifest_rejects_pricing_changed_without_new_identity(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, manifest = manifest_bundle
    manifest["provider"]["pricing"]["input_usd_per_million_tokens"] = "1.01"
    _write_manifest(path, manifest)

    with pytest.raises(FunctionalV1ManifestError) as captured:
        FunctionalV1Manifest.load(path)

    assert captured.value.reason_code == "pricing-record-mismatch"


def _reseal_pricing(pricing: dict[str, object]) -> None:
    payload = {key: value for key, value in pricing.items() if key != "identity"}
    pricing["identity"] = str(
        TypedDigest.from_bytes(DigestKind.PRICING_RECORD, canonical_json_bytes(payload))
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_usd_per_million_tokens", "1"),
        ("input_usd_per_million_tokens", "1001.0"),
        ("output_usd_per_million_tokens", "0.0"),
        ("retrieved_at_utc", "2026-01-01T00:00:00.000Z"),
        ("retrieved_at_utc", "2027-06-01T00:00:00Z"),
        ("effective_until_utc", "2026-01-01T00:00:00Z"),
        ("source_url", "http://provider.example/pricing"),
        ("source_url", "https://provider.example/pricing?plan=team"),
        ("unit", "usd-per-token"),
        ("currency", "EUR"),
        ("schema_version", 2),
    ],
)
def test_manifest_rejects_invalid_pricing_fields_before_identity(
    manifest_bundle: tuple[Path, dict[str, object]],
    field: str,
    value: object,
) -> None:
    # The identity is resealed over the mutated content, so only the field
    # rules — not digest drift — can produce the rejection.
    path, manifest = manifest_bundle
    pricing = manifest["provider"]["pricing"]
    pricing[field] = value
    _reseal_pricing(pricing)
    _write_manifest(path, manifest)

    with pytest.raises(FunctionalV1ManifestError) as captured:
        FunctionalV1Manifest.load(path)

    assert captured.value.reason_code == "invalid-pricing-record"


def test_manifest_rejects_unparseable_pricing_identity(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, manifest = manifest_bundle
    manifest["provider"]["pricing"]["identity"] = "not-a-typed-digest"
    _write_manifest(path, manifest)

    with pytest.raises(FunctionalV1ManifestError) as captured:
        FunctionalV1Manifest.load(path)

    assert captured.value.reason_code == "invalid-pricing-record"


def test_manifest_rejects_pricing_with_missing_field(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, manifest = manifest_bundle
    del manifest["provider"]["pricing"]["source_url"]
    _write_manifest(path, manifest)

    with pytest.raises(FunctionalV1ManifestError) as captured:
        FunctionalV1Manifest.load(path)

    assert captured.value.reason_code == "invalid-manifest-schema"

@pytest.mark.parametrize(
    ("section", "field", "value", "reason_code"),
    [
        ("execution", "max_parallel", 2, "fixed-envelope-mismatch"),
        ("limits", "cpu_cores_per_trial", 3, "fixed-envelope-mismatch"),
        ("limits", "memory_mib_per_trial", 8_192, "fixed-envelope-mismatch"),
        ("limits", "writable_disk_mib_per_trial", 16_384, "fixed-envelope-mismatch"),
        ("limits", "wall_time_seconds_per_trial", 3_600, "fixed-envelope-mismatch"),
        ("limits", "requests_per_trial", 65, "fixed-envelope-mismatch"),
        ("limits", "provider_tokens_per_trial", 0, "invalid-token-threshold"),
        ("limits", "provider_tokens_per_trial", 500_001, "invalid-token-threshold"),
        ("limits", "stop_after_cost_usd_per_trial", "0.00", "invalid-cost-threshold"),
        ("limits", "stop_after_cost_usd_per_trial", "20.01", "invalid-cost-threshold"),
    ],
)
def test_manifest_rejects_values_outside_the_accepted_envelope(
    manifest_bundle: tuple[Path, dict[str, object]],
    section: str,
    field: str,
    value: object,
    reason_code: str,
) -> None:
    path, manifest = manifest_bundle
    manifest[section][field] = value
    _write_manifest(path, manifest)

    with pytest.raises(FunctionalV1ManifestError) as captured:
        FunctionalV1Manifest.load(path)

    assert captured.value.reason_code == reason_code


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"provider_api_key": "secret"}),
        lambda value: value["provider"].update({"temperature": 0}),
        lambda value: value["conditions"]["omp"].update({"arguments": ["--unsafe"]}),
        lambda value: value["scenarios"].pop("angular-reading-time"),
    ],
)
def test_manifest_rejects_secrets_harness_controls_and_partial_matrices(
    manifest_bundle: tuple[Path, dict[str, object]],
    mutation: object,
) -> None:
    path, manifest = manifest_bundle
    mutation(manifest)
    _write_manifest(path, manifest)

    with pytest.raises(FunctionalV1ManifestError):
        FunctionalV1Manifest.load(path)


def test_manifest_rejects_duplicate_fields(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, _ = manifest_bundle
    path.write_text(
        path.read_text(encoding="utf-8") + "schema_version: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(FunctionalV1ManifestError) as captured:
        FunctionalV1Manifest.load(path)

    assert captured.value.reason_code == "invalid-manifest-yaml"


def test_manifest_rejects_absolute_escaping_and_symlink_references(
    manifest_bundle: tuple[Path, dict[str, object]],
) -> None:
    path, manifest = manifest_bundle
    manifest["conditions"]["omp"]["path"] = "/tmp/omp.json"
    _write_manifest(path, manifest)
    with pytest.raises(FunctionalV1ManifestError, match="absolute or escaping"):
        FunctionalV1Manifest.load(path)

    target = path.parent / "locks/omp.condition.json"
    link = path.parent / "omp-link.json"
    link.symlink_to(target)
    manifest["conditions"]["omp"]["path"] = "omp-link.json"
    _write_manifest(path, manifest)
    with pytest.raises(FunctionalV1ManifestError, match="symlink"):
        FunctionalV1Manifest.load(path)


def test_published_template_has_the_exact_fixed_shape() -> None:
    template_path = (
        Path(__file__).resolve().parents[3] / "templates/functional-v1-manifest-v1.yaml"
    )
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))

    assert tuple(template["scenarios"]) == SCENARIOS
    assert tuple(template["conditions"]) == CONDITIONS
    assert template["execution"] == {
        "max_parallel": 3,
        "network_policy": "proxy-only-v1",
    }
    assert template["limits"] == {
        "requests_per_trial": 64,
        "provider_tokens_per_trial": 375_000,
        "stop_after_cost_usd_per_trial": "5.00",
        "wall_time_seconds_per_trial": 1_800,
        "cpu_cores_per_trial": 2,
        "memory_mib_per_trial": 4_096,
        "writable_disk_mib_per_trial": 8_192,
    }


def test_functional_v1_provisioning_records_sealed_store_images(
    tmp_path: Path,
    manifest_bundle: tuple[Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = execution.FunctionalV1Home(tmp_path / "home")
    runtime = execution.NativeFunctionalV1Runtime(home)
    monkeypatch.setattr(execution, "_native_host", lambda: {})
    monkeypatch.setattr(execution, "_scenario_package", lambda *_: tmp_path)
    store_ids = {
        "agent": "sha256:" + "1" * 64,
        "capture": "sha256:" + "2" * 64,
        "verifier": "sha256:" + "3" * 64,
    }
    provisioned: list[str] = []

    def fake_scenario_provisioning(
        *_: object,
        manifest_output: Path,
        qualification_record: Path | None,
        **__: object,
    ) -> dict[str, object]:
        assert qualification_record is None
        manifest_output.write_bytes(
            canonical_json_bytes(
                {
                    "runtime_images": [
                        {"role": role, "image": {"id": image_id}}
                        for role, image_id in store_ids.items()
                    ]
                }
            )
        )
        provisioned.append(str(manifest_output))
        return {"manifest_sha256": "provisioning-manifest:sha256:" + "0" * 64}

    def unexpected_scenario_build(*arguments: object, **_: object) -> None:
        raise AssertionError(
            f"coordinator must not rebuild sealed store images: {arguments}"
        )

    monkeypatch.setattr(
        execution, "provision_scenario_package", fake_scenario_provisioning
    )
    monkeypatch.setattr(execution, "_build_image", unexpected_scenario_build)

    class _ConditionBoundaryReached(RuntimeError):
        pass

    def stop_at_conditions(*_: object, **__: object) -> Path:
        raise _ConditionBoundaryReached

    registry = MappingProxyType(
        {
            name: (
                dataclasses.replace(definition, provision=stop_at_conditions)
                if definition.provision is not None
                else definition
            )
            for name, definition in execution.CONDITION_REGISTRY.items()
        }
    )
    monkeypatch.setattr(execution, "CONDITION_REGISTRY", registry)

    with pytest.raises(_ConditionBoundaryReached):
        runtime._provision(manifest)

    assert len(provisioned) == 4


class _PreflightBoundaryReached(RuntimeError):
    pass


@pytest.mark.parametrize("require_provider_credential", [True, False])
def test_functional_v1_preflight_uses_diagnostic_integration_boundary(
    tmp_path: Path,
    manifest_bundle: tuple[Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
    require_provider_credential: bool,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = execution.FunctionalV1Home(tmp_path / "home")
    home.store_manifest_inputs(manifest)
    runtime = execution.NativeFunctionalV1Runtime(home)
    inventory = execution.ProvisioningInventory(
        TypedDigest.from_bytes(DigestKind.PROVISIONING_MANIFEST, b"inventory"),
        {
            "scenarios": {
                name: {"provisioning_manifest": "unused"} for name in SCENARIOS
            }
        },
        tmp_path / "inventory.json",
    )
    if require_provider_credential:
        monkeypatch.setenv("MODEL_BENCHMARK_PROVIDER_API_KEY", "secret")
    else:
        monkeypatch.delenv("MODEL_BENCHMARK_PROVIDER_API_KEY", raising=False)
    monkeypatch.setattr(execution, "_native_host", lambda: {})
    monkeypatch.setattr(execution, "_load_inventory", lambda *_: inventory)
    monkeypatch.setattr(execution, "_verify_inventory_images", lambda *_: None)
    monkeypatch.setattr(execution, "_scenario_package", lambda *_: tmp_path)

    def stop_at_scenario_preflight(
        *_: object,
        mode: str,
        qualification_record: Path | None,
        **__: object,
    ) -> dict[str, object]:
        assert mode == "integration"
        assert qualification_record is None
        raise _PreflightBoundaryReached

    monkeypatch.setattr(
        execution, "preflight_scenario_package", stop_at_scenario_preflight
    )

    with pytest.raises(_PreflightBoundaryReached):
        runtime._preflight(
            manifest, require_provider_credential=require_provider_credential
        )
