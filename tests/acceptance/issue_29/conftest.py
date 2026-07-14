from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_qualification import (
    review_signing_bytes,
    technical_signing_bytes,
)
from model_benchmark.declarations.schemas import SchemaRegistry


ROOT = Path(__file__).resolve().parents[3]
CLI = Path(sys.executable).with_name("model-benchmark")
REGISTRY = SchemaRegistry(ROOT / "schemas")


@dataclass
class QualificationCase:
    package: Path
    technical_path: Path
    review_path: Path
    output_path: Path
    technical: dict[str, Any]
    review: dict[str, Any]


def run_scenario(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, "--json", "scenario", *arguments],
        capture_output=True,
        text=True,
        timeout=1500,
        check=False,
    )


def write_document(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(value))


def sign_review(review: dict[str, Any]) -> None:
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
    reviewer["authentication"]["value"] = (
        f"ed25519:{encoded_key}:{encoded_signature}"
    )


def sign_technical(technical: dict[str, Any]) -> str:
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


def scaffold(
    destination: Path,
    *,
    scenario_id: str,
    ecosystem: str,
    visibility: str = "private",
) -> Path:
    completed = run_scenario(
        "scaffold",
        str(destination),
        "--scenario-id",
        scenario_id,
        "--ecosystem",
        ecosystem,
        "--visibility",
        visibility,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return destination


def build_qualification_case(tmp_path: Path) -> QualificationCase:
    package = scaffold(
        tmp_path / "package",
        scenario_id="acceptance/qualified-scenario",
        ecosystem="python-data-engineering",
        visibility="public",
    )
    completed = run_scenario("lock", str(package))
    assert completed.returncode == 0, completed.stderr or completed.stdout
    lock_data = (package / "scenario.lock.json").read_bytes()
    lock = json.loads(lock_data)
    manifest = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
    package_record = lock["package"]
    resolved = lock["resolved_inputs"]
    instruction = next(
        entry["sha256"]
        for entry in package_record["files"]
        if entry["path"] == "instruction.md"
    )
    baseline_vector = manifest["verification"]["qualification"][
        "baseline_score_vector"
    ]
    reference_vector = manifest["verification"]["qualification"][
        "reference_score_vector"
    ]

    def run_record(environment: str, outcome: str, vector: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "environment_id": environment,
            "outcome": outcome,
            "reward_score_vector": deepcopy(vector),
            "structured_score_vector": deepcopy(vector),
        }

    technical: dict[str, Any] = {
        "candidate_status": "technically-qualified",
        "harbor": lock["harbor"],
        "identities": lock["identities"],
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
            "instruction_sha256": instruction,
            "package_payload_sha256": package_record["payload_sha256"],
            "pristine": resolved["pristine"],
            "scenario_baseline": resolved["scenario_baseline"],
            "seed_inputs": resolved["seed_inputs"],
        },
    }
    review: dict[str, Any] = {
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
    sign_review(review)
    sign_technical(technical)
    technical_path = tmp_path / "technical-qualification.json"
    review_path = tmp_path / "scenario-review.json"
    write_document(technical_path, technical)
    write_document(review_path, review)
    return QualificationCase(
        package=package,
        technical_path=technical_path,
        review_path=review_path,
        output_path=tmp_path / "package-qualification-record.json",
        technical=technical,
        review=review,
    )


@pytest.fixture
def scenario_runner():
    return run_scenario


@pytest.fixture
def scenario_scaffold():
    return scaffold


@pytest.fixture
def document_writer():
    return write_document


@pytest.fixture
def technical_signer():
    return sign_technical


@pytest.fixture
def review_signer():
    return sign_review


@pytest.fixture
def qualification_case(tmp_path: Path) -> QualificationCase:
    return build_qualification_case(tmp_path)
