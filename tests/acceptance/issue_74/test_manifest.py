from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

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
        "network_policy": "guarded-public-web-v1",
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
    template_path = Path(__file__).resolve().parents[3] / "templates/functional-v1-manifest-v1.yaml"
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))

    assert tuple(template["scenarios"]) == SCENARIOS
    assert tuple(template["conditions"]) == CONDITIONS
    assert template["execution"] == {
        "max_parallel": 3,
        "network_policy": "guarded-public-web-v1",
    }
    assert template["limits"] == {
        "requests_per_trial": 64,
        "provider_tokens_per_trial": 100_000,
        "stop_after_cost_usd_per_trial": "5.00",
        "wall_time_seconds_per_trial": 1_800,
        "cpu_cores_per_trial": 2,
        "memory_mib_per_trial": 4_096,
        "writable_disk_mib_per_trial": 8_192,
    }
