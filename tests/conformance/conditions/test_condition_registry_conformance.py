"""Registry-driven conformance for the Condition seam (issue #90).

Every host-side consumer resolves per-condition behavior through
``condition_registry.CONDITIONS``; these tests pin the registry's shape,
the pinned lock identities, field-level lock-mutation rejection, the
byte-exact entrypoint scripts, and each launch shim's no-argument exit
contract.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_benchmark.declarations import functional_v1
from model_benchmark.declarations.canonical import (
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime import condition_registry, hermes, raw_api
from model_benchmark.runtime.conditions import (
    HARNESS_CONDITIONS,
    ConditionAdapterError,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY = condition_registry.CONDITIONS
_REJECTION_REASON_CODES = frozenset(
    {"invalid-condition-lock", "condition-unqualified", "condition-lock-mismatch"}
)
_DEFAULT_ENTRYPOINT_SCRIPT = (
    "export PYTHONHOME=$ROOT/usr/local\n"
    "export PYTHONPATH=$ROOT/opt/model-benchmark-runtime\n"
    "exec $LOADER --library-path $LIBRARY_PATH $ROOT/usr/local/bin/python3.12 -m "
    'model_benchmark.runtime.condition_image "$@"\n'
)
_HERMES_ENTRYPOINT_SCRIPT = (
    "export PYTHONHOME=$ROOT/usr\n"
    "export PYTHONPATH=$ROOT/opt/model-benchmark-runtime:$ROOT/opt/hermes/.venv/lib/python3.13/site-packages\n"
    "exec $LOADER --library-path $LIBRARY_PATH $ROOT/usr/bin/python3 -m "
    'model_benchmark.runtime.condition_image "$@"\n'
)
_SHIM_REQUIRED_ARGUMENTS = {
    "omp": ("--omp", "--artifact-identity"),
    "opencode": ("--opencode", "--artifact-identity"),
    "hermes": ("--artifact-identity",),
    "raw-api": ("--artifact-identity", "--target-path"),
}


def _lock_value(name: str) -> dict[str, object]:
    value = load_canonical_json(_REGISTRY[name].lock_path().read_bytes())
    assert isinstance(value, dict)
    return dict(value)


def _mutated(value: object) -> object:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return f"{value}-mutated"
    if isinstance(value, list):
        return [*value, "mutated"]
    if isinstance(value, dict):
        return {**value, "mutated-field": True}
    raise AssertionError(f"unsupported lock field type: {type(value).__name__}")


def _mutation_cases(names: tuple[str, ...]) -> list[pytest.ParameterSet]:
    return [
        pytest.param(name, field, id=f"{name}-{field}")
        for name in names
        for field in sorted(_lock_value(name))
    ]


def test_registry_names_match_functional_v1_conditions_in_order() -> None:
    assert tuple(_REGISTRY) == functional_v1.CONDITIONS
    for name, definition in _REGISTRY.items():
        assert definition.name == name


def test_registry_harness_conditions_match_seam_constant() -> None:
    assert condition_registry.HARNESS_CONDITIONS == HARNESS_CONDITIONS


@pytest.mark.parametrize("name", tuple(_REGISTRY))
def test_definition_lock_and_shim_paths_resolve_to_files(name: str) -> None:
    definition = _REGISTRY[name]
    assert definition.lock_path().is_file()
    assert definition.launch_shim_path().is_file()


@pytest.mark.parametrize("name", sorted(HARNESS_CONDITIONS))
def test_harness_definition_carries_every_verb(name: str) -> None:
    definition = _REGISTRY[name]
    assert definition.kind == "harness"
    assert definition.validate_lock is not None
    assert definition.provision is not None
    assert definition.seal_process is not None
    assert definition.evaluate_qualification is not None


def test_raw_api_is_scenario_target_baseline() -> None:
    definition = _REGISTRY["raw-api"]
    assert definition.kind == "baseline"
    assert definition.requires_scenario_target is True


@pytest.mark.parametrize("name", tuple(_REGISTRY))
def test_pinned_lock_identity_recomputes_over_lock_bytes(name: str) -> None:
    definition = _REGISTRY[name]
    data, value, identity = definition.load_lock()
    assert data == definition.lock_path().read_bytes()
    assert dict(value) == load_canonical_json(data)
    assert identity.kind is DigestKind.FUNCTIONAL_V1_CONDITION
    assert identity == TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data)


@pytest.mark.parametrize(
    ("name", "field"), _mutation_cases(tuple(sorted(HARNESS_CONDITIONS)))
)
def test_harness_adapter_rejects_field_level_lock_mutation(
    name: str, field: str
) -> None:
    definition = _REGISTRY[name]
    lock = _lock_value(name)
    lock[field] = _mutated(lock[field])
    mutated = canonical_json_bytes(lock)
    assert definition.validate_lock is not None
    with pytest.raises(ConditionAdapterError) as rejection:
        definition.validate_lock(mutated)
    assert rejection.value.reason_code in _REJECTION_REASON_CODES


@pytest.mark.parametrize(("name", "field"), _mutation_cases(("raw-api",)))
def test_raw_api_field_level_lock_mutation_changes_pinned_identity(
    name: str, field: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = _REGISTRY[name]
    _, _, pinned_identity = definition.load_lock()
    lock = _lock_value(name)
    lock[field] = _mutated(lock[field])
    mutated_path = tmp_path / "raw-api-mutated.condition.json"
    mutated_path.write_bytes(canonical_json_bytes(lock))
    monkeypatch.setattr(raw_api, "raw_api_condition_lock_path", lambda: mutated_path)
    _, _, identity = definition.load_lock()
    assert identity.kind is DigestKind.FUNCTIONAL_V1_CONDITION
    assert identity != pinned_identity


def test_entrypoint_scripts_are_pinned_verbatim() -> None:
    assert condition_registry._DEFAULT_ENTRYPOINT_SCRIPT == _DEFAULT_ENTRYPOINT_SCRIPT
    assert condition_registry._HERMES_ENTRYPOINT_SCRIPT == _HERMES_ENTRYPOINT_SCRIPT


def test_definitions_wire_entrypoint_scripts_and_image_base() -> None:
    assert _REGISTRY["hermes"].entrypoint_script == _HERMES_ENTRYPOINT_SCRIPT
    assert _REGISTRY["hermes"].image_base == hermes.HERMES_IMAGE_REFERENCE
    for name in ("omp", "opencode", "raw-api"):
        assert _REGISTRY[name].entrypoint_script == _DEFAULT_ENTRYPOINT_SCRIPT
        assert _REGISTRY[name].image_base is None


@pytest.mark.parametrize("name", tuple(_REGISTRY))
def test_launch_shim_rejects_missing_arguments_without_import_failure(
    name: str, tmp_path: Path
) -> None:
    shim = _REGISTRY[name].launch_shim_path()
    completed = subprocess.run(
        [sys.executable, str(shim)],
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_PROJECT_ROOT / "src"),
        },
        timeout=30,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    assert completed.returncode == 2
    assert "ImportError" not in stderr
    assert "ModuleNotFoundError" not in stderr
    assert "the following arguments are required" in stderr
    for argument in _SHIM_REQUIRED_ARGUMENTS[name]:
        assert argument in stderr
