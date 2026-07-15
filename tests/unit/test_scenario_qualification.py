from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenarios import ScenarioPackageError
from model_benchmark.declarations.scenario_qualification import (
    review_signing_bytes,
    technical_signing_bytes,
    validate_scenario_state_transition,
)
from model_benchmark.declarations.schemas import SchemaRegistry
from model_benchmark.runtime import scenario_qualification as runtime_qualification
from model_benchmark.runtime.scenario_qualification import (
    _environment_identity,
    _validate_structured_result,
    _vector,
)


ROOT = Path(__file__).resolve().parents[2]
CLI = Path(sys.executable).with_name("model-benchmark")
REGISTRY = SchemaRegistry(ROOT / "schemas")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, "--json", "scenario", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_numeric_projection_includes_every_declared_domain_score() -> None:
    names = (
        "acceptance_score",
        "correctness_score",
        "regression_score",
        "task_success",
    )
    assert _vector(
        {
            "acceptance_score": 1,
            "correctness_score": 0.5,
            "regression_score": 1,
            "task_success": 1,
            "checks": [{"id": "acceptance", "status": "pass"}],
        },
        names,
    ) == [
        {"name": "acceptance_score", "value": "1"},
        {"name": "correctness_score", "value": "0.5"},
        {"name": "regression_score", "value": "1"},
        {"name": "task_success", "value": "1"},
    ]


def test_structured_result_requires_complete_group_evidence_and_consistent_success() -> (
    None
):
    groups = (
        ("acceptance", "acceptance", True, "acceptance", Decimal("1"), None),
        ("regression", "regression", True, "regression", Decimal("1"), None),
    )
    valid: dict[str, object] = {
        "acceptance_score": 1,
        "checks": [
            {
                "evidence": ["capture/capture.json"],
                "id": "acceptance",
                "status": "pass",
            },
            {"evidence": ["tests/test.sh"], "id": "regression", "status": "pass"},
        ],
        "domain_scores": {},
        "regression_score": 1,
        "required_group_statuses": {"acceptance": "pass", "regression": "pass"},
        "task_success": True,
        "verifier_complete": True,
    }

    _validate_structured_result(valid, groups)

    for mutation in (
        lambda value: value.update({"checks": []}),
        lambda value: value.update({"required_group_statuses": {"acceptance": "pass"}}),
        lambda value: value.update({"task_success": False}),
        lambda value: value.update({"acceptance_score": 0}),
        lambda value: value.update({"regression_score": 0}),
        lambda value: value.update({"verifier_complete": False}),
    ):
        malformed = deepcopy(valid)
        mutation(malformed)
        with pytest.raises(
            ScenarioPackageError,
            match="structured verifier|Check Group|task_success|score",
        ):
            _validate_structured_result(malformed, groups)


def test_environment_identity_comes_from_fresh_agent_capture_and_verifier_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial = {
        "trial_name": "example-task--nop--1",
        "started_at": "2026-07-14T10:00:00Z",
        "finished_at": "2026-07-14T10:01:00Z",
    }

    def event(identity: str, project: str, service: str) -> str:
        return json.dumps(
            {
                "Actor": {
                    "Attributes": {
                        "com.docker.compose.project": project,
                        "com.docker.compose.service": service,
                    },
                    "ID": identity,
                },
                "Type": "container",
                "Action": "create",
                "id": identity,
            }
        )

    agent_project = "example-task--nop--1__env"
    verifier_project = "example-task--nop--1__verifier__a1b2c3d4"
    events = "\n".join(
        (
            event("agent-container", agent_project, "main"),
            event("capture-container", agent_project, "capture"),
            event("verifier-container", verifier_project, "main"),
        )
    )
    monkeypatch.setattr(
        runtime_qualification,
        "_run",
        lambda command, *, timeout, cwd=None: subprocess.CompletedProcess(
            command, 0, stdout=events, stderr=""
        ),
    )

    identity = _environment_identity(trial)

    assert identity.startswith("docker-environment:sha256:")
    monkeypatch.setattr(
        runtime_qualification,
        "_run",
        lambda command, *, timeout, cwd=None: subprocess.CompletedProcess(
            command,
            0,
            stdout=event("agent-container", agent_project, "main"),
            stderr="",
        ),
    )
    with pytest.raises(
        ScenarioPackageError, match="fresh agent, capture, and verifier"
    ):
        _environment_identity(trial)


def _write_document(path: Path, value: dict[str, object]) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _sign_review(review: dict[str, Any]) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("42" * 32))
    public_key = private_key.public_key().public_bytes_raw()
    encoded_key = base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("=")
    reviewer = review["reviewer"]
    reviewer["identity"] = "ed25519:sha256:" + hashlib.sha256(public_key).hexdigest()
    reviewer["authentication"] = {
        "kind": "signature",
        "value": f"ed25519:{encoded_key}:",
    }
    signature = private_key.sign(review_signing_bytes(review))
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    reviewer["authentication"]["value"] = f"ed25519:{encoded_key}:{encoded_signature}"


def _sign_technical(technical: dict[str, Any]) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("24" * 32))
    public_key = private_key.public_key().public_bytes_raw()
    encoded_key = base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("=")
    identity = "ed25519:sha256:" + hashlib.sha256(public_key).hexdigest()
    technical["worker"] = {
        "authentication": {
            "kind": "signature",
            "value": f"ed25519:{encoded_key}:",
        },
        "environment": "fresh-harbor-agent-and-separate-verifier",
        "identity": identity,
    }
    signature = private_key.sign(technical_signing_bytes(technical))
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    technical["worker"]["authentication"]["value"] = (
        f"ed25519:{encoded_key}:{encoded_signature}"
    )
    return identity


def _qualification_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict[str, Any], dict[str, Any]]:
    package = tmp_path / "package"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/qualified-scenario",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "public",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    locked = _run("lock", str(package))
    assert locked.returncode == 0, locked.stderr or locked.stdout
    lock_data = (package / "scenario.lock.json").read_bytes()
    lock = json.loads(lock_data)
    manifest = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
    package_record = lock["package"]
    resolved = lock["resolved_inputs"]
    instruction_digest = next(
        entry["sha256"]
        for entry in package_record["files"]
        if entry["path"] == "instruction.md"
    )
    baseline_vector = manifest["verification"]["qualification"]["baseline_score_vector"]
    reference_vector = manifest["verification"]["qualification"][
        "reference_score_vector"
    ]

    def run_record(
        environment_id: str,
        outcome: str,
        vector: list[dict[str, str]],
    ) -> dict[str, object]:
        return {
            "environment_id": environment_id,
            "outcome": outcome,
            "reward_score_vector": deepcopy(vector),
            "structured_score_vector": deepcopy(vector),
        }

    technical: dict[str, object] = {
        "candidate_status": "technically-qualified",
        "harbor": lock["harbor"],
        "identities": lock["identities"],
        "provisioning": {
            "manifest_sha256": "provisioning-manifest:sha256:" + "1" * 64,
            "projected_task_sha256": "harbor-task:sha256:" + "2" * 64,
            "projection_sha256": "artifact:sha256:" + "3" * 64,
        },
        "package_payload_sha256": package_record["payload_sha256"],
        "qualified_at": "2026-07-13T20:00:00Z",
        "runs": {
            "baseline": run_record(
                "fresh-baseline",
                "declared-failure",
                baseline_vector,
            ),
            "handoffs": [
                {
                    "classification": "valid_harness_outcome",
                    "environment_id": "harbor-malformed-environment",
                    "kind": "malformed",
                    "task_success": False,
                },
                {
                    "classification": "valid_harness_outcome",
                    "environment_id": "harbor-unsafe-environment",
                    "kind": "unsafe",
                    "task_success": False,
                },
            ],
            "hidden_marker": {
                "environment_id": "fresh-hidden-marker",
                "status": "passed",
            },
            "no_download": True,
            "reference": [
                run_record("fresh-reference-1", "passed", reference_vector),
                run_record("fresh-reference-2", "passed", reference_vector),
            ],
            "score_mismatch": {
                "environment_id": "harbor-score-mismatch-environment",
                "status": "passed",
            },
        },
        "schema": REGISTRY.envelope(
            "model-benchmark/scenario-technical-qualification",
            1,
        ),
        "standard_v1": lock["standard_v1"],
        "validated_inputs": {
            "datasets": resolved["datasets"],
            "images": resolved["images"],
            "instruction_sha256": instruction_digest,
            "package_payload_sha256": package_record["payload_sha256"],
            "pristine": resolved["pristine"],
            "scenario_baseline": resolved["scenario_baseline"],
            "seed_inputs": resolved["seed_inputs"],
        },
    }
    review: dict[str, object] = {
        "checklist_version": 1,
        "identities": lock["identities"],
        "judgment": "approve",
        "package_lock_sha256": str(
            TypedDigest.from_bytes(DigestKind.PACKAGE_LOCK, lock_data)
        ),
        "package_payload_sha256": package_record["payload_sha256"],
        "reasons": {
            "answer_leakage": "Hidden assets are absent from the agent-visible manifest.",
            "brief_verifier_alignment": "The verifier checks the Developer Brief.",
            "difficulty_and_boundedness": "The task is bounded and appropriately difficult.",
            "disclosure_handling": "Public disclosure is appropriate for this fixture.",
            "implementation_neutrality": "No implementation is prescribed.",
            "professional_realism": "The task represents professional repository work.",
            "provenance_and_licensing": "Provenance and licensing are declared.",
        },
        "reviewed_at": "2026-07-13T21:00:00Z",
        "reviewer": {
            "principal_identity": "urn:model-benchmark:author:independent-reviewer",
            "authentication": {
                "kind": "repository-identity",
                "value": "https://github.com/example/reviews/qualified-scenario",
            },
            "identity": "independent-reviewer",
            "independence_attested": True,
        },
        "schema": REGISTRY.envelope("model-benchmark/scenario-review", 1),
    }
    _sign_review(review)
    _sign_technical(technical)
    technical_path = tmp_path / "technical-qualification.json"
    review_path = tmp_path / "scenario-review.json"
    output = tmp_path / "package-qualification-record.json"
    _write_document(technical_path, technical)
    _write_document(review_path, review)
    return package, technical_path, review_path, output, technical, review


def _qualify(
    package: Path,
    technical: Path,
    review: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return _run(
        "qualify",
        str(package),
        "--technical-evidence",
        str(technical),
        "--trusted-worker-identity",
        json.loads(technical.read_text(encoding="utf-8"))["worker"]["identity"],
        "--review",
        str(review),
        "--trusted-reviewer-identity",
        json.loads(review.read_text(encoding="utf-8"))["reviewer"]["identity"],
        "--output",
        str(output),
    )


def test_qualification_seals_one_deterministic_suite_owned_record(
    tmp_path: Path,
) -> None:
    package, technical, review, output, _, _ = _qualification_inputs(tmp_path)

    first = _qualify(package, technical, review, output)

    assert first.returncode == 0, first.stderr or first.stdout
    first_bytes = output.read_bytes()
    record = REGISTRY.validate_bytes(first_bytes)
    assert record["state"] == "package_qualified"
    assert record["lifecycle"] == {"from": "candidate", "to": "package_qualified"}
    assert "provider" not in first_bytes.decode("utf-8")
    assert "model_id" not in first_bytes.decode("utf-8")

    second = _qualify(package, technical, review, output)

    assert second.returncode == 0, second.stderr or second.stdout
    assert output.read_bytes() == first_bytes


def test_failed_qualification_cannot_erase_a_prior_immutable_record(
    tmp_path: Path,
) -> None:
    package, technical, review_path, output, _, review = _qualification_inputs(tmp_path)
    first = _qualify(package, technical, review_path, output)
    assert first.returncode == 0, first.stderr or first.stdout
    original = output.read_bytes()
    review["judgment"] = "reject"
    _sign_review(review)
    _write_document(review_path, review)

    rejected = _qualify(package, technical, review_path, output)

    assert rejected.returncode != 0
    assert (
        json.loads(rejected.stdout)["classification"] == "independent-review-rejected"
    )
    assert output.read_bytes() == original
    retained = list((output.parent / "scenario-reviews/public").glob("*.json"))
    assert len(retained) == 2
    assert {
        json.loads(path.read_text(encoding="utf-8"))["judgment"] for path in retained
    } == {
        "approve",
        "reject",
    }


def test_suite_must_name_the_trusted_technical_worker(tmp_path: Path) -> None:
    package, technical, review, output, _, _ = _qualification_inputs(tmp_path)

    completed = _run(
        "qualify",
        str(package),
        "--technical-evidence",
        str(technical),
        "--trusted-worker-identity",
        "ed25519:sha256:" + "0" * 64,
        "--review",
        str(review),
        "--trusted-reviewer-identity",
        json.loads(review.read_text(encoding="utf-8"))["reviewer"]["identity"],
        "--output",
        str(output),
    )

    assert completed.returncode != 0
    assert (
        json.loads(completed.stdout)["classification"] == "untrusted-technical-worker"
    )
    assert not output.exists()


def test_suite_must_name_the_trusted_independent_reviewer(tmp_path: Path) -> None:
    package, technical, review, output, _, _ = _qualification_inputs(tmp_path)

    completed = _run(
        "qualify",
        str(package),
        "--technical-evidence",
        str(technical),
        "--trusted-worker-identity",
        json.loads(technical.read_text(encoding="utf-8"))["worker"]["identity"],
        "--review",
        str(review),
        "--trusted-reviewer-identity",
        "ed25519:sha256:" + "0" * 64,
        "--output",
        str(output),
    )

    assert completed.returncode != 0
    assert (
        json.loads(completed.stdout)["classification"]
        == "untrusted-independent-reviewer"
    )
    assert not output.exists()


def test_qualification_rejects_noncanonical_authoritative_evidence(
    tmp_path: Path,
) -> None:
    package, technical, review, output, _, _ = _qualification_inputs(tmp_path)
    value = json.loads(technical.read_text(encoding="utf-8"))
    technical.write_text(json.dumps(value, indent=2), encoding="utf-8")

    completed = _qualify(package, technical, review, output)

    assert completed.returncode != 0
    assert (
        json.loads(completed.stdout)["classification"]
        == "invalid-technical-qualification"
    )
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "classification"),
    [
        (
            lambda technical, review: review.update({"judgment": "reject"}),
            "independent-review-rejected",
        ),
        (
            lambda technical, review: technical["runs"]["reference"][0][
                "reward_score_vector"
            ][0].update({"value": "0"}),
            "invalid-infrastructure",
        ),
        (
            lambda technical, review: review["reasons"].update(
                {"professional_realism": "tampered after signing"}
            ),
            "unsigned-independent-review",
        ),
        (
            lambda technical, review: review.update(
                {"reviewed_at": "2026-07-13T19:00:00Z"}
            ),
            "invalid-qualification-order",
        ),
    ],
    ids=[
        "rejected-review",
        "reward-projection-mismatch",
        "tampered-signature",
        "review-predates-qualification",
    ],
)
def test_qualification_fails_closed_without_leaving_a_record(
    tmp_path: Path,
    mutation: Any,
    classification: str,
) -> None:
    package, technical_path, review_path, output, technical, review = (
        _qualification_inputs(tmp_path)
    )
    mutation(technical, review)
    if classification == "independent-review-rejected":
        _sign_review(review)
    if classification == "invalid-infrastructure":
        _sign_technical(technical)
    _write_document(technical_path, deepcopy(technical))
    _write_document(review_path, deepcopy(review))

    completed = _qualify(package, technical_path, review_path, output)

    assert completed.returncode != 0
    assert json.loads(completed.stdout)["classification"] == classification
    assert not output.exists()
    if classification == "independent-review-rejected":
        retained = list((output.parent / "scenario-reviews/public").glob("*.json"))
        assert len(retained) == 1
        assert (
            json.loads(retained[0].read_text(encoding="utf-8"))["judgment"] == "reject"
        )


def test_qualification_cannot_overwrite_its_review_input(tmp_path: Path) -> None:
    package, technical, review, _, _, _ = _qualification_inputs(tmp_path)
    review_bytes = review.read_bytes()

    completed = _qualify(package, technical, review, review)

    assert completed.returncode != 0
    assert (
        json.loads(completed.stdout)["classification"] == "invalid-qualification-output"
    )
    assert review.read_bytes() == review_bytes


def test_scenario_lifecycle_is_closed() -> None:
    validate_scenario_state_transition("authoring_target", "candidate")
    validate_scenario_state_transition("private_slot", "candidate")
    validate_scenario_state_transition("candidate", "package_qualified")
    validate_scenario_state_transition("package_qualified", "roster_selected")
    validate_scenario_state_transition("roster_selected", "suite_sealed")

    with pytest.raises(Exception, match="cannot move"):
        validate_scenario_state_transition("candidate", "suite_sealed")


def test_package_author_cannot_serve_as_independent_reviewer(
    tmp_path: Path,
) -> None:
    package, technical, review_path, output, _, review = _qualification_inputs(tmp_path)
    manifest = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
    review["reviewer"]["principal_identity"] = manifest["provenance"]["authors"][0]
    _sign_review(review)
    _write_document(review_path, review)

    completed = _qualify(package, technical, review_path, output)

    assert completed.returncode != 0
    assert json.loads(completed.stdout)["classification"] == "non-independent-review"
    assert not output.exists()
