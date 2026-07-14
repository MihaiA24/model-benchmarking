from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any

from model_benchmark.declarations.identities import (
    DigestKind,
    IdentityError,
    ScenarioIdentity,
    ScoreContractIdentity,
    TypedDigest,
    VerifierIdentity,
)
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


SCENARIO_SCHEMA_NAME = "model-benchmark/scenario-package"
SCENARIO_SCHEMA_VERSION = 1


class ScenarioContractError(ValueError):
    """The authored seven-section Scenario declaration is not strict."""


def _typed_digest(value: object, kind: DigestKind, location: str) -> None:
    if not isinstance(value, str):
        raise ScenarioContractError(f"{location} must be a typed digest")
    try:
        digest = TypedDigest.parse(value)
    except IdentityError as error:
        raise ScenarioContractError(str(error)) from error
    if digest.kind is not kind:
        raise ScenarioContractError(
            f"{location} must use {kind.value}:sha256 identity"
        )


def _component_version(
    identity: type[Any],
    value: object,
    location: str,
) -> None:
    if not isinstance(value, str):
        raise ScenarioContractError(f"{location} must be SemVer")
    try:
        identity.from_payload(value, {"contract": location})
    except IdentityError as error:
        raise ScenarioContractError(str(error)) from error


def _safe_relative_path(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScenarioContractError(f"{location} must be a non-empty path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "" in path.parts
        or "." in path.parts
        or path.as_posix() != value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ScenarioContractError(
            f"{location} must be a normalized portable package-relative path"
        )
    return value


def _weight(value: object, location: str) -> Decimal:
    if not isinstance(value, str):
        raise ScenarioContractError(f"{location} must be exact decimal text")
    try:
        weight = Decimal(value)
    except InvalidOperation as error:
        raise ScenarioContractError(f"invalid {location}") from error
    if not weight.is_finite() or weight <= 0 or weight > 1:
        raise ScenarioContractError(f"{location} must be in (0, 1]")
    return weight


def validate_scenario_manifest(
    manifest: dict[str, Any],
    *,
    registry: SchemaRegistry,
) -> None:
    """Apply the published strict schema and semantic cross-field checks."""
    try:
        registry.validate_value(
            manifest,
            name=SCENARIO_SCHEMA_NAME,
            version=SCENARIO_SCHEMA_VERSION,
        )
    except SchemaValidationError as error:
        raise ScenarioContractError(str(error)) from error

    scenario = manifest["scenario"]
    repository = manifest["repository"]
    instruction = manifest["instruction"]
    verification = manifest["verification"]
    provenance = manifest["provenance"]

    _component_version(ScenarioIdentity, scenario["version"], "scenario.version")
    _component_version(
        VerifierIdentity,
        verification["verifier"]["version"],
        "verification.verifier.version",
    )
    _component_version(
        ScoreContractIdentity,
        verification["score_contract"]["version"],
        "verification.score_contract.version",
    )

    pristine = repository["pristine"]
    _typed_digest(pristine["tree_sha256"], DigestKind.SOURCE_TREE, "pristine tree")
    _typed_digest(
        repository["baseline_tree_sha256"],
        DigestKind.SOURCE_TREE,
        "Scenario Baseline",
    )
    archive_path = pristine["archive"]
    archive_digest = pristine["archive_sha256"]
    if (archive_path is None) != (archive_digest is None):
        raise ScenarioContractError(
            "pristine archive path and digest must be jointly present or absent"
        )
    if archive_path is not None:
        archive_path = _safe_relative_path(
            archive_path,
            "repository.pristine.archive",
        )
        if not archive_path.startswith("seed/"):
            raise ScenarioContractError(
                "repository.pristine.archive must remain under seed/"
            )
        _typed_digest(
            archive_digest,
            DigestKind.ARTIFACT,
            "repository.pristine.archive_sha256",
        )

    declared_paths: set[str] = set()
    for collection, label in (
        (repository["seed_inputs"], "seed input"),
        (repository["datasets"], "dataset"),
    ):
        identifiers: set[str] = set()
        for entry in collection:
            path = _safe_relative_path(entry["path"], f"{label}.path")
            expected_root = "data/" if label == "dataset" else "seed/"
            if not path.startswith(expected_root):
                raise ScenarioContractError(
                    f"{label}.path must remain under {expected_root}"
                )
            if path in declared_paths:
                raise ScenarioContractError(f"duplicate declared input path: {path}")
            declared_paths.add(path)
            _typed_digest(entry["sha256"], DigestKind.ARTIFACT, label)
            if label == "seed input" and entry["kind"] == "asset":
                _safe_relative_path(
                    entry["destination"],
                    "seed input.destination",
                )
            elif label == "dataset":
                identifier = entry["id"]
                if identifier in identifiers:
                    raise ScenarioContractError(f"duplicate dataset ID: {identifier}")
                identifiers.add(identifier)

    _typed_digest(
        instruction["sha256"],
        DigestKind.ARTIFACT,
        "Developer Brief",
    )

    submission = manifest["submission"]
    if submission["kind"] == "git-patch":
        for field in ("allowed_paths", "protected_paths"):
            for index, value in enumerate(submission[field]):
                _safe_relative_path(value, f"submission.{field}[{index}]")
    else:
        for index, value in enumerate(submission["allowed_paths"]):
            _safe_relative_path(value, f"submission.allowed_paths[{index}]")
        _typed_digest(
            submission["schema"]["sha256"],
            DigestKind.SCHEMA,
            "non-patch output schema",
        )
        output_schema = submission["schema"]
        try:
            entry = registry.entry(output_schema["name"], output_schema["version"])
        except SchemaValidationError as error:
            raise ScenarioContractError(str(error)) from error
        if output_schema["sha256"] != entry.sha256:
            raise ScenarioContractError(
                "non-patch output schema digest does not match the catalog"
            )

    totals = {"acceptance": Decimal(0), "regression": Decimal(0)}
    group_ids: set[str] = set()
    evidence_keys: set[str] = set()
    for group in verification["check_groups"]:
        identifier = group["id"]
        evidence_key = group["evidence_key"]
        if identifier in group_ids or evidence_key in evidence_keys:
            raise ScenarioContractError(
                "Check Group IDs and evidence keys must be independently unique"
            )
        group_ids.add(identifier)
        evidence_keys.add(evidence_key)
        weight = _weight(group["weight"], f"Check Group {identifier!r} weight")
        if group["class"] in totals:
            totals[group["class"]] += weight
    if totals != {"acceptance": Decimal(1), "regression": Decimal(1)}:
        raise ScenarioContractError(
            "acceptance and regression weights must each sum exactly to one"
        )
    domain_scores = verification["domain_scores"]
    domain_score_names = [score["name"] for score in domain_scores]
    mapped_groups = [
        group_id
        for score in domain_scores
        for group_id in score["check_groups"]
    ]
    domain_group_ids = {
        group["id"]
        for group in verification["check_groups"]
        if group["class"] == "domain"
    }
    if (
        len(domain_score_names) != len(set(domain_score_names))
        or len(mapped_groups) != len(set(mapped_groups))
        or set(mapped_groups) != domain_group_ids
    ):
        raise ScenarioContractError(
            "domain scores must uniquely and completely map domain Check Groups"
        )
    groups_by_id = {group["id"]: group for group in verification["check_groups"]}
    for score in domain_scores:
        total = sum(
            (
                _weight(groups_by_id[group_id]["weight"], group_id)
                for group_id in score["check_groups"]
            ),
            Decimal(0),
        )
        if total != Decimal(1):
            raise ScenarioContractError(
                f"domain score {score['name']!r} weights must sum exactly to one"
            )
    expected_names = {
        "acceptance_score",
        "regression_score",
        "task_success",
        *domain_score_names,
    }
    for field in ("baseline_score_vector", "reference_score_vector"):
        vector = verification["qualification"][field]
        names = [entry["name"] for entry in vector]
        if names != sorted(names) or set(names) != expected_names:
            raise ScenarioContractError(
                f"qualification.{field} must be sorted and complete"
            )
    baseline = {
        entry["name"]: entry["value"]
        for entry in verification["qualification"]["baseline_score_vector"]
    }
    reference = {
        entry["name"]: entry["value"]
        for entry in verification["qualification"]["reference_score_vector"]
    }
    if baseline["task_success"] != "0" or reference["task_success"] != "1":
        raise ScenarioContractError(
            "qualification vectors must declare baseline failure and Reference success"
        )
    authors = provenance["authors"]
    if not authors or len(authors) != len(set(authors)):
        raise ScenarioContractError("provenance authors must be non-empty and unique")
