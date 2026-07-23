from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from model_benchmark.declarations.canonical import (
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.declarations.identities import (
    DigestKind,
    IdentityError,
    TypedDigest,
)
from model_benchmark.declarations.provider_routes import (
    parse_provider_protocol,
    provider_protocol_spec,
)
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError
from model_benchmark.runtime.dry_launch_provider import (
    DRY_LAUNCH_RESPONSE,
)
from model_benchmark.runtime.execution import (
    CELL_SCHEDULE,
    HarborCellExecutor,
    NativeFunctionalV1Runtime,
    _check_pricing_window,
    _cleanup_owned,
    _load_inventory,
    _remove_sealed_tree,
    _resource_inventory,
    _runtime_source_root,
    _tree_digest,
    _utc_now,
    _write_run_provenance,
    FunctionalV1Coordinator,
)
from model_benchmark.runtime.functional_v1 import FunctionalV1Home, _immutable_write


_SCHEMA_NAME = "model-benchmark/functional-v1-dry-launch-qualification"
_SCHEMAS = SchemaRegistry(schema_root_path())
_CATALOG_URL = "https://models.dev/api.json"
_PROVIDER_ID = "opencode-go"
_REFERENCE_MODEL = "deepseek-v4-flash"
_LINK_NAME = re.compile(r"^[a-zA-Z0-9_.-]+$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESULT_BUNDLE = re.compile(r"^result-bundle:sha256:[0-9a-f]{64}$")
_MANIFEST = re.compile(r"^functional-v1-manifest:sha256:[0-9a-f]{64}$")
_RESOLVED_MANIFEST = re.compile(r"^resolved-v1-manifest:sha256:[0-9a-f]{64}$")


class DryLaunchQualificationError(ValueError):
    """Dry-launch evidence is incomplete, unsafe, stale, or malformed."""


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _link_state(name: str) -> str:
    if _LINK_NAME.fullmatch(name) is None:
        raise DryLaunchQualificationError("worker uplink name is invalid")
    path = Path("/sys/class/net") / name / "operstate"
    try:
        state = path.read_text(encoding="ascii").strip()
    except OSError as error:
        raise DryLaunchQualificationError(
            f"worker uplink state is unavailable: {name}"
        ) from error
    if state not in {"down", "up"}:
        raise DryLaunchQualificationError(
            f"worker uplink {name} has unsupported state {state!r}"
        )
    return state


def _live_route_status(base_url: str, protocol: str) -> int:
    spec = provider_protocol_spec(parse_provider_protocol(protocol))
    route_url = f"{base_url.rstrip('/')}{spec.endpoint_path}"
    request = urllib.request.Request(
        route_url,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "model-benchmark-dry-launch-qualification/1",
            **spec.required_headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except (OSError, urllib.error.URLError) as error:
        raise DryLaunchQualificationError(
            f"provider route is unreachable without credentials: {route_url}: {error}"
        ) from error


_RATE_FIELDS = (
    ("input", "input_usd_per_million_tokens"),
    ("output", "output_usd_per_million_tokens"),
    ("cache_read", "cache_read_usd_per_million_tokens"),
)


def _catalog_rates(value: Mapping[str, object], model: str) -> dict[str, Decimal]:
    try:
        rates = {target: Decimal(str(value[source])) for source, target in _RATE_FIELDS}
    except (KeyError, InvalidOperation) as error:
        raise DryLaunchQualificationError(
            f"catalog pricing is malformed for {model}"
        ) from error
    if any(not rate.is_finite() or rate <= 0 for rate in rates.values()):
        raise DryLaunchQualificationError(f"catalog pricing is invalid for {model}")
    return rates


def _catalog_limits(value: Mapping[str, object], model: str) -> tuple[int, int]:
    limits = value.get("limit")
    if not isinstance(limits, Mapping):
        raise DryLaunchQualificationError(f"catalog limits are absent for {model}")
    context_tokens = limits.get("context")
    output_tokens = limits.get("output")
    if any(
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 10_000_000
        for limit in (context_tokens, output_tokens)
    ):
        raise DryLaunchQualificationError(f"catalog limits are invalid for {model}")
    return context_tokens, output_tokens


def _catalog_tiers(cost: Mapping[str, object], model: str) -> list[dict[str, object]]:
    raw_tiers = cost.get("tiers", [])
    if not isinstance(raw_tiers, list) or len(raw_tiers) > 8:
        raise DryLaunchQualificationError(
            f"catalog pricing tiers are invalid for {model}"
        )
    tiers: list[dict[str, object]] = []
    for raw_tier in raw_tiers:
        if not isinstance(raw_tier, Mapping):
            raise DryLaunchQualificationError(
                f"catalog pricing tier is malformed for {model}"
            )
        selector = raw_tier.get("tier")
        if (
            not isinstance(selector, Mapping)
            or selector.get("type") != "context"
            or not isinstance(selector.get("size"), int)
            or isinstance(selector.get("size"), bool)
            or int(selector["size"]) <= 0
        ):
            raise DryLaunchQualificationError(
                f"catalog pricing tier selector is invalid for {model}"
            )
        rates = _catalog_rates(raw_tier, model)
        tiers.append(
            {
                "input_tokens_gt": int(selector["size"]),
                **{field: format(rate, "f") for field, rate in rates.items()},
            }
        )
    return tiers


def _pricing_tiers_match(
    manifest_tiers: object, catalog_tiers: Sequence[Mapping[str, object]]
) -> bool:
    if not isinstance(manifest_tiers, list) or len(manifest_tiers) != len(
        catalog_tiers
    ):
        return False
    for manifest_tier, catalog_tier in zip(manifest_tiers, catalog_tiers):
        if not isinstance(manifest_tier, Mapping):
            return False
        if manifest_tier.get("input_tokens_gt") != catalog_tier["input_tokens_gt"]:
            return False
        if any(
            Decimal(str(manifest_tier[field])) != Decimal(str(catalog_tier[field]))
            for _, field in _RATE_FIELDS
        ):
            return False
    return True


def _manifest_catalog_entry(
    manifest: FunctionalV1Manifest,
    *,
    catalog_document_sha256: str,
    provider: Mapping[str, object],
    route_status: int,
) -> dict[str, object]:
    manifest_provider = manifest.value["provider"]
    if not isinstance(manifest_provider, Mapping):
        raise DryLaunchQualificationError("manifest provider projection is malformed")
    pricing = manifest_provider["pricing"]
    if not isinstance(pricing, Mapping):
        raise DryLaunchQualificationError("manifest pricing projection is malformed")
    model = str(manifest_provider["model"])
    models = provider.get("models")
    catalog_model = models.get(model) if isinstance(models, Mapping) else None
    if not isinstance(catalog_model, Mapping) or catalog_model.get("id") != model:
        raise DryLaunchQualificationError(
            f"model is absent from {_PROVIDER_ID}: {model}"
        )
    protocol = parse_provider_protocol(manifest_provider["protocol"])
    protocol_spec = provider_protocol_spec(protocol)
    model_provider = catalog_model.get("provider")
    catalog_package = (
        model_provider.get("npm")
        if isinstance(model_provider, Mapping)
        else provider.get("npm")
    )
    if catalog_package != protocol_spec.ai_sdk_package:
        raise DryLaunchQualificationError(f"provider protocol drift for {model}")
    catalog_context_tokens, catalog_output_tokens = _catalog_limits(
        catalog_model, model
    )
    cost = catalog_model.get("cost")
    if not isinstance(cost, Mapping):
        raise DryLaunchQualificationError(f"catalog pricing is absent for {model}")
    catalog_rates = _catalog_rates(cost, model)
    if any(
        catalog_rates[field] != Decimal(str(pricing[field]))
        for _, field in _RATE_FIELDS
    ):
        raise DryLaunchQualificationError(f"base pricing drift for {model}")
    catalog_tiers = _catalog_tiers(cost, model)
    if not _pricing_tiers_match(pricing["tiers"], catalog_tiers):
        raise DryLaunchQualificationError(f"tiered pricing drift for {model}")
    if pricing["source_url"] != _CATALOG_URL:
        raise DryLaunchQualificationError(f"pricing source drift for {model}")
    if pricing["source_snapshot_sha256"] != catalog_document_sha256:
        raise DryLaunchQualificationError(f"pricing snapshot drift for {model}")
    if provider.get("api") != manifest_provider["base_url"]:
        raise DryLaunchQualificationError(f"provider route drift for {model}")
    if not 400 <= route_status < 500 or route_status == 404:
        raise DryLaunchQualificationError(
            f"provider route did not reject an unauthenticated probe for {model}: "
            f"HTTP {route_status}"
        )
    _check_pricing_window(manifest)
    return {
        "base_url": manifest_provider["base_url"],
        "catalog_cache_read_usd_per_million_tokens": format(
            catalog_rates["cache_read_usd_per_million_tokens"], "f"
        ),
        "catalog_context_tokens": catalog_context_tokens,
        "catalog_input_usd_per_million_tokens": format(
            catalog_rates["input_usd_per_million_tokens"], "f"
        ),
        "catalog_output_usd_per_million_tokens": format(
            catalog_rates["output_usd_per_million_tokens"], "f"
        ),
        "catalog_output_tokens": catalog_output_tokens,
        "catalog_tiers": catalog_tiers,
        "effective_from_utc": pricing["effective_from_utc"],
        "effective_until_utc": pricing["effective_until_utc"],
        "live_route_status": route_status,
        "manifest": manifest.source_path.name,
        "manifest_identity": str(manifest.identity),
        "model": model,
        "pricing_identity": pricing["identity"],
        "pricing_source_snapshot_sha256": pricing["source_snapshot_sha256"],
        "pricing_source_url": pricing["source_url"],
        "resolved_manifest_identity": str(manifest.resolved_identity),
        "source_yaml_sha256": manifest.source_yaml_sha256,
        "status": "passed",
    }


def collect_catalog_validation(
    manifest_paths: Sequence[Path], *, output: Path
) -> dict[str, object]:
    if len(manifest_paths) != 4:
        raise DryLaunchQualificationError("catalog validation requires four manifests")
    manifests = [FunctionalV1Manifest.load(path.resolve()) for path in manifest_paths]
    if len({manifest.source_path.name for manifest in manifests}) != 4:
        raise DryLaunchQualificationError("catalog manifest paths must be distinct")
    request = urllib.request.Request(
        _CATALOG_URL,
        headers={"User-Agent": "model-benchmark-dry-launch-qualification/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            catalog_bytes = response.read()
    except (OSError, urllib.error.URLError) as error:
        raise DryLaunchQualificationError(
            f"cannot retrieve {_CATALOG_URL}: {error}"
        ) from error
    try:
        catalog = json.loads(catalog_bytes)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DryLaunchQualificationError("models.dev returned invalid JSON") from error
    provider = catalog.get(_PROVIDER_ID) if isinstance(catalog, dict) else None
    if not isinstance(provider, Mapping):
        raise DryLaunchQualificationError(f"catalog provider is absent: {_PROVIDER_ID}")
    catalog_document_sha256 = _sha256(catalog_bytes)
    statuses = {
        (str(provider_value["base_url"]), str(provider_value["protocol"])): (
            _live_route_status(
                str(provider_value["base_url"]), str(provider_value["protocol"])
            )
        )
        for manifest in manifests
        for provider_value in (manifest.value["provider"],)
    }
    value = {
        "catalog_document_sha256": catalog_document_sha256,
        "manifests": [
            _manifest_catalog_entry(
                manifest,
                catalog_document_sha256=catalog_document_sha256,
                provider=provider,
                route_status=statuses[
                    (
                        str(manifest.value["provider"]["base_url"]),
                        str(manifest.value["provider"]["protocol"]),
                    )
                ],
            )
            for manifest in manifests
        ],
        "provider_id": _PROVIDER_ID,
        "retrieved_at_utc": _utc_now(),
        "schema_version": 2,
        "source_url": _CATALOG_URL,
        "status": "passed",
    }
    _immutable_write(
        output.resolve(), canonical_json_bytes(value), allow_identical=False
    )
    return value


def _load_catalog_validation(
    path: Path, manifests: Sequence[FunctionalV1Manifest]
) -> dict[str, object]:
    data = path.resolve().read_bytes()
    try:
        value = load_canonical_json(data)
    except Exception as error:
        raise DryLaunchQualificationError(
            "catalog validation is not canonical JSON"
        ) from error
    if (
        not isinstance(value, dict)
        or value.get("status") != "passed"
        or value.get("schema_version") != 2
        or value.get("source_url") != _CATALOG_URL
    ):
        raise DryLaunchQualificationError("catalog validation did not pass")
    records = value.get("manifests")
    if not isinstance(records, list) or len(records) != 4:
        raise DryLaunchQualificationError(
            "catalog validation has no four-manifest inventory"
        )
    expected = {
        manifest.source_path.name: (
            str(manifest.identity),
            str(manifest.resolved_identity),
            manifest.source_yaml_sha256,
        )
        for manifest in manifests
    }
    observed: dict[str, tuple[object, object, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise DryLaunchQualificationError("catalog manifest record is malformed")
        observed[str(record.get("manifest"))] = (
            record.get("manifest_identity"),
            record.get("resolved_manifest_identity"),
            record.get("source_yaml_sha256"),
        )
    if observed != expected:
        raise DryLaunchQualificationError(
            "catalog validation is stale for current manifests"
        )
    return value


def _bundle_cell_record(
    workspace_root: Path,
    cell: Mapping[str, object],
) -> dict[str, object]:
    cell_id = str(cell["cell_id"])
    cell_root = workspace_root / "cells" / cell_id
    start = load_canonical_json((cell_root / "start.json").read_bytes())
    terminal = load_canonical_json((cell_root / "terminal.json").read_bytes())
    inventory_bytes = (cell_root / "bundle/inventory.json").read_bytes()
    inventory = load_canonical_json(inventory_bytes)
    identity_text = (cell_root / "bundle.identity").read_text(encoding="ascii").strip()
    expected_identity = str(
        TypedDigest.from_bytes(DigestKind.RESULT_BUNDLE, inventory_bytes)
    )
    if (
        identity_text != expected_identity
        or terminal.get("result_bundle_identity") != identity_text
    ):
        raise DryLaunchQualificationError(f"sealed Result Bundle mismatch: {cell_id}")
    if terminal.get("evidence_valid") is not True:
        raise DryLaunchQualificationError(f"invalid cell evidence: {cell_id}")
    if (
        terminal.get("disposition") != "valid_completed"
        or terminal.get("terminal_phase") != "verification"
    ):
        raise DryLaunchQualificationError(f"invalid dry-launch lifecycle: {cell_id}")
    details = terminal.get("details")
    artifacts = inventory.get("artifacts") if isinstance(inventory, dict) else None
    if not isinstance(details, dict) or not isinstance(artifacts, list):
        raise DryLaunchQualificationError(f"malformed sealed evidence: {cell_id}")
    present = {
        str(entry.get("path"))
        for entry in artifacts
        if isinstance(entry, dict) and entry.get("status") == "present"
    }
    required = {
        "capture/capture.json",
        "harbor/result.json",
        "proxy/proxy.jsonl",
        "verifier/verifier-result.json",
    }
    provider_requests = details.get("provider_requests")
    if (
        not isinstance(provider_requests, int)
        or isinstance(provider_requests, bool)
        or provider_requests < 1
        or not required <= present
        or details.get("external_egress") != "disabled"
        or details.get("external_provider_requests") != 0
        or details.get("provider_substitution") != "loopback-deterministic-v1"
        or details.get("cleanup_after") != []
    ):
        raise DryLaunchQualificationError(f"incomplete dry-launch lifecycle: {cell_id}")
    return {
        "cell_id": cell_id,
        "condition": cell["condition"],
        "disposition": terminal["disposition"],
        "evidence_valid": True,
        "lifecycle": {
            "bundle_sealed": True,
            "cleanup_complete": True,
            "condition_exited": details.get("harbor_exit_code") is not None,
            "condition_started": isinstance(start, dict),
            "proxy_request_observed": True,
            "trusted_submission_capture": True,
            "verifier_completed": True,
        },
        "provider_requests": provider_requests,
        "provider_tokens": details.get("provider_tokens", 0),
        "reason_code": terminal["reason_code"],
        "result_bundle_identity": identity_text,
        "scenario": cell["scenario"],
        "terminal_phase": terminal["terminal_phase"],
    }


def execute_qualification(
    reference_manifest_path: Path,
    manifest_paths: Sequence[Path],
    *,
    home_path: Path,
    catalog_validation_path: Path,
    draft_path: Path,
    worker_uplink: str,
) -> dict[str, object]:
    if len(manifest_paths) != 4:
        raise DryLaunchQualificationError(
            "dry launch requires four supported manifests"
        )
    manifests = [FunctionalV1Manifest.load(path.resolve()) for path in manifest_paths]
    catalog = _load_catalog_validation(catalog_validation_path, manifests)
    reference = FunctionalV1Manifest.load(reference_manifest_path.resolve())
    if str(reference.value["provider"]["model"]) != _REFERENCE_MODEL:
        raise DryLaunchQualificationError(
            "DeepSeek V4 Flash must be the structural reference"
        )
    if str(reference.identity) not in {
        str(manifest.identity) for manifest in manifests
    }:
        raise DryLaunchQualificationError(
            "reference manifest is absent from supported manifests"
        )
    _check_pricing_window(reference)
    if _link_state(worker_uplink) != "down":
        raise DryLaunchQualificationError(
            "worker uplink must remain down during dry launch"
        )

    started_at = _utc_now()
    home = FunctionalV1Home(home_path.resolve())
    runtime = NativeFunctionalV1Runtime(home)
    workspace = None
    projection = None
    executor = None
    try:
        with home.coordinator_lease():
            projection = runtime._preflight(
                reference, require_provider_credential=False
            )
            if _link_state(worker_uplink) != "down":
                raise DryLaunchQualificationError(
                    "worker uplink changed during preflight"
                )
            workspace = home.create_workspace(reference)
            inventory = _load_inventory(home, reference)
            _write_run_provenance(workspace, projection, inventory)
            executor = HarborCellExecutor(
                reference,
                inventory,
                projection.packages,
                workspace,
                dry_launch=True,
            )
            outcomes = FunctionalV1Coordinator(workspace, executor).execute(
                CELL_SCHEDULE
            )
            if len(outcomes) != len(CELL_SCHEDULE):
                raise DryLaunchQualificationError(
                    "dry launch did not execute all 16 cells"
                )
            _cleanup_owned(workspace.run_id)
            runtime._drain_cell_evidence(workspace, CELL_SCHEDULE)
            cells = [
                _bundle_cell_record(workspace.root, cell) for cell in CELL_SCHEDULE
            ]
            if _resource_inventory(workspace.run_id):
                raise DryLaunchQualificationError("dry-launch Docker resources remain")
            if (workspace.root / "run-record.json").exists():
                raise DryLaunchQualificationError("dry launch created a Run Record")
            if _link_state(worker_uplink) != "down":
                raise DryLaunchQualificationError(
                    "worker uplink changed during execution"
                )
            completed_at = _utc_now()
            local_requests = sum(int(cell["provider_requests"]) for cell in cells)
            value = {
                "catalog_validation": catalog,
                "cells": cells,
                "execution": {
                    "completed_at_utc": completed_at,
                    "manifest_identity": str(reference.identity),
                    "manifest_source_sha256": reference.source_yaml_sha256,
                    "resolved_manifest_identity": str(reference.resolved_identity),
                    "runtime_tree_digest": _tree_digest(_runtime_source_root()),
                    "started_at_utc": started_at,
                },
                "local_provider": {
                    "external_cost_usd": "0",
                    "external_provider_requests": 0,
                    "implementation_sha256": _sha256(
                        (
                            Path(__file__).with_name("dry_launch_provider.py")
                        ).read_bytes()
                    ),
                    "local_provider_requests": local_requests,
                    "network": "loopback-only",
                    "response_sha256": _sha256(DRY_LAUNCH_RESPONSE.encode("utf-8")),
                    "substitution": "loopback-deterministic-v1",
                },
                "network": {
                    "after_execution": "down",
                    "before_execution": "down",
                    "external_egress_observed": 0,
                    "proxy_network": "internal",
                    "restored": None,
                    "worker_uplink": worker_uplink,
                },
                "schema": _SCHEMAS.envelope(_SCHEMA_NAME, 2),
                "schema_version": 2,
                "summary": {
                    "cleanup_complete": True,
                    "invalid_infrastructure": 0,
                    "invalid_integrity": 0,
                    "run_record_created": False,
                    "sealed_bundles": len(cells),
                    "task_success_required": False,
                    "terminal_lifecycles": len(cells),
                },
            }
            _immutable_write(
                draft_path.resolve(), canonical_json_bytes(value), allow_identical=False
            )
            return value
    finally:
        if executor is not None:
            executor.terminate_all()
        if workspace is not None:
            _cleanup_owned(workspace.run_id)
            shutil.rmtree(workspace.root, ignore_errors=True)
        if projection is not None:
            _remove_sealed_tree(projection.temporary_root)


def _validate_record(value: Mapping[str, object]) -> None:
    cells = value.get("cells")
    summary = value.get("summary")
    local_provider = value.get("local_provider")
    network = value.get("network")
    execution = value.get("execution")
    if value.get("schema_version") != 2 or not isinstance(cells, list):
        raise DryLaunchQualificationError("dry-launch record header is malformed")
    expected_ids = [str(cell["cell_id"]) for cell in CELL_SCHEDULE]
    if [
        cell.get("cell_id") for cell in cells if isinstance(cell, dict)
    ] != expected_ids:
        raise DryLaunchQualificationError(
            "dry-launch record does not contain the 16-cell schedule"
        )
    for cell in cells:
        if not isinstance(cell, dict):
            raise DryLaunchQualificationError("dry-launch cell is malformed")
        lifecycle = cell.get("lifecycle")
        if (
            not isinstance(lifecycle, dict)
            or set(lifecycle.values()) != {True}
            or cell.get("evidence_valid") is not True
            or not isinstance(cell.get("provider_requests"), int)
            or int(cell["provider_requests"]) < 1
            or _RESULT_BUNDLE.fullmatch(str(cell.get("result_bundle_identity"))) is None
            or cell.get("disposition") != "valid_completed"
            or cell.get("terminal_phase") != "verification"
        ):
            raise DryLaunchQualificationError(
                f"dry-launch cell lifecycle is invalid: {cell.get('cell_id')}"
            )
    if not isinstance(summary, dict) or summary != {
        "cleanup_complete": True,
        "invalid_infrastructure": 0,
        "invalid_integrity": 0,
        "run_record_created": False,
        "sealed_bundles": 16,
        "task_success_required": False,
        "terminal_lifecycles": 16,
    }:
        raise DryLaunchQualificationError("dry-launch summary is invalid")
    if (
        not isinstance(local_provider, dict)
        or local_provider.get("external_cost_usd") != "0"
        or local_provider.get("external_provider_requests") != 0
        or local_provider.get("network") != "loopback-only"
        or local_provider.get("substitution") != "loopback-deterministic-v1"
    ):
        raise DryLaunchQualificationError("local-provider substitution is invalid")
    if (
        not isinstance(network, dict)
        or network.get("before_execution") != "down"
        or network.get("after_execution") != "down"
        or network.get("restored") != "up"
        or network.get("external_egress_observed") != 0
        or network.get("proxy_network") != "internal"
    ):
        raise DryLaunchQualificationError("dry-launch network proof is invalid")
    if (
        not isinstance(execution, dict)
        or _MANIFEST.fullmatch(str(execution.get("manifest_identity"))) is None
        or _RESOLVED_MANIFEST.fullmatch(
            str(execution.get("resolved_manifest_identity"))
        )
        is None
        or _SHA256.fullmatch(str(execution.get("manifest_source_sha256"))) is None
    ):
        raise DryLaunchQualificationError("dry-launch execution identity is invalid")


def seal_qualification(
    draft_path: Path,
    *,
    output: Path,
    worker_uplink: str,
) -> TypedDigest:
    if _link_state(worker_uplink) != "up":
        raise DryLaunchQualificationError("worker uplink restoration is not verified")
    try:
        draft = load_canonical_json(draft_path.resolve().read_bytes())
    except Exception as error:
        raise DryLaunchQualificationError(
            "dry-launch draft is not canonical JSON"
        ) from error
    if not isinstance(draft, dict):
        raise DryLaunchQualificationError("dry-launch draft is not an object")
    network = draft.get("network")
    if not isinstance(network, dict) or network.get("worker_uplink") != worker_uplink:
        raise DryLaunchQualificationError("dry-launch draft uplink identity is invalid")
    network["restored"] = "up"
    draft["sealed_at_utc"] = _utc_now()
    _validate_record(draft)
    data = canonical_json_bytes(draft)
    try:
        _SCHEMAS.validate_bytes(data)
    except SchemaValidationError as error:
        raise DryLaunchQualificationError(str(error)) from error
    identity = TypedDigest.from_bytes(DigestKind.DRY_LAUNCH_QUALIFICATION, data)
    output = output.resolve()
    identity_path = output.with_suffix(".identity")
    inventory_path = output.with_suffix(".sha256")
    _immutable_write(output, data, allow_identical=False)
    _immutable_write(
        identity_path, f"{identity}\n".encode("ascii"), allow_identical=False
    )
    inventory = (
        f"{hashlib.sha256(data).hexdigest()}  {output.name}\n"
        f"{hashlib.sha256((str(identity) + chr(10)).encode('ascii')).hexdigest()}  {identity_path.name}\n"
    )
    _immutable_write(inventory_path, inventory.encode("ascii"), allow_identical=False)
    return identity


def inspect_qualification(path: Path) -> dict[str, object]:
    path = path.resolve()
    data = path.read_bytes()
    try:
        value = load_canonical_json(data)
    except Exception as error:
        raise DryLaunchQualificationError(
            "qualification record is not canonical JSON"
        ) from error
    if not isinstance(value, dict):
        raise DryLaunchQualificationError("qualification record is not an object")
    identity_path = path.with_suffix(".identity")
    identity_text = identity_path.read_text(encoding="ascii")
    try:
        identity = TypedDigest.parse(identity_text.removesuffix("\n"))
    except IdentityError as error:
        raise DryLaunchQualificationError(str(error)) from error
    expected = TypedDigest.from_bytes(DigestKind.DRY_LAUNCH_QUALIFICATION, data)
    if identity != expected or identity_text != f"{expected}\n":
        raise DryLaunchQualificationError(
            "qualification identity does not match record bytes"
        )
    try:
        _SCHEMAS.validate_bytes(data)
    except SchemaValidationError as error:
        raise DryLaunchQualificationError(str(error)) from error
    _validate_record(value)
    return {
        "external_cost_usd": "0",
        "identity": str(identity),
        "local_provider_requests": value["local_provider"]["local_provider_requests"],
        "outcome": "passed",
        "sealed_bundles": 16,
        "terminal_lifecycles": 16,
        "uplink_restored": True,
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Functional V1 no-spend dry-launch qualification"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog")
    catalog.add_argument("--manifest", action="append", required=True)
    catalog.add_argument("--output", required=True, type=Path)

    execute = subparsers.add_parser("execute")
    execute.add_argument("reference", type=Path)
    execute.add_argument("--manifest", action="append", required=True)
    execute.add_argument("--home", required=True, type=Path)
    execute.add_argument("--catalog-validation", required=True, type=Path)
    execute.add_argument("--draft", required=True, type=Path)
    execute.add_argument("--worker-uplink", default="mb-host0")

    seal = subparsers.add_parser("seal")
    seal.add_argument("--draft", required=True, type=Path)
    seal.add_argument("--output", required=True, type=Path)
    seal.add_argument("--worker-uplink", default="mb-host0")

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("record", type=Path)

    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "catalog":
            value: object = collect_catalog_validation(
                _paths(arguments.manifest), output=arguments.output
            )
            result = {
                "manifests": len(value["manifests"]),
                "outcome": "passed",
                "output": str(arguments.output),
            }
        elif arguments.command == "execute":
            value = execute_qualification(
                arguments.reference,
                _paths(arguments.manifest),
                home_path=arguments.home,
                catalog_validation_path=arguments.catalog_validation,
                draft_path=arguments.draft,
                worker_uplink=arguments.worker_uplink,
            )
            result = {
                "cells": len(value["cells"]),
                "draft": str(arguments.draft),
                "outcome": "executed",
            }
        elif arguments.command == "seal":
            identity = seal_qualification(
                arguments.draft,
                output=arguments.output,
                worker_uplink=arguments.worker_uplink,
            )
            result = {
                "identity": str(identity),
                "outcome": "sealed",
                "output": str(arguments.output),
            }
        else:
            result = inspect_qualification(arguments.record)
    except (DryLaunchQualificationError, OSError, ValueError) as error:
        print(f"dry-launch qualification: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
