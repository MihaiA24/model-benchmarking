from __future__ import annotations

# pyright: reportMissingImports=false

import argparse
import json
import math
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from model_benchmark.declarations.identities import TypedDigest
from model_benchmark.declarations.scenarios import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry
from model_benchmark.evidence.pytest_acceptance import _tree_digest
from model_benchmark.evidence.verification import (
    VerificationCase,
    VerificationInput,
    verify_checksum_manifest,
    write_verification_artifacts,
)


def _summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "sample_count": len(values),
        "minimum_ms": round(ordered[0], 6),
        "median_ms": round(statistics.median(ordered), 6),
        "p95_nearest_rank_ms": round(
            ordered[math.ceil(0.95 * len(ordered)) - 1], 6
        ),
        "maximum_ms": round(ordered[-1], 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--samples", type=int, default=30)
    arguments = parser.parse_args()
    if arguments.samples < 1:
        raise SystemExit("--samples must be positive")

    root = arguments.repo.resolve()
    actual_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_commit != arguments.expected_commit:
        raise SystemExit(
            f"evidence checkout is {actual_commit}, expected {arguments.expected_commit}"
        )
    artifact = root / "artifacts/acceptance/issue-29/verification.json"
    manifest = root / "artifacts/acceptance/issue-29/sha256sums.txt"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    inputs = [
        VerificationInput(
            name=item["name"], digest=TypedDigest.parse(item["digest"])
        )
        for item in payload["input_identities"]
    ]
    cases = [
        VerificationCase(id=item["id"], outcome=item["outcome"])
        for item in payload["case_results"]
    ]

    publication_samples: list[float] = []
    with tempfile.TemporaryDirectory(prefix="issue53-publish-bench-") as temporary:
        project_root = Path(temporary)
        for _ in range(arguments.samples):
            started = time.perf_counter()
            outputs = write_verification_artifacts(
                project_root=project_root,
                schema_root=schema_root_path(),
                issue=29,
                command=payload["command"],
                inputs=inputs,
                cases=cases,
            )
            publication_samples.append((time.perf_counter() - started) * 1000)
            verify_checksum_manifest(project_root, outputs[1])

    source_paths = [
        root / "src",
        root / "tests/conftest.py",
        root / "tests/acceptance/issue_29",
    ]
    for optional in ("tests/fixtures", "profiles", "scaffolds"):
        candidate = root / optional
        if candidate.exists():
            source_paths.append(candidate)
    expected_source_digest = next(
        item["digest"]
        for item in payload["input_identities"]
        if item["name"] == "acceptance-source-tree"
    )
    registry = SchemaRegistry(schema_root_path())
    consumption_samples: list[float] = []
    source_matches: list[bool] = []
    for _ in range(arguments.samples):
        started = time.perf_counter()
        actual_source_digest = str(_tree_digest(source_paths, root))
        verify_checksum_manifest(root, manifest)
        registry.validate_path(artifact)
        parsed = json.loads(artifact.read_text(encoding="utf-8"))
        source_matches.append(
            actual_source_digest == expected_source_digest
            and len(parsed["case_results"]) == 19
        )
        consumption_samples.append((time.perf_counter() - started) * 1000)

    result = {
        "evidence_commit": actual_commit,
        "artifact_publication": {
            "raw_samples_ms": [round(value, 6) for value in publication_samples],
            "summary": _summary(publication_samples),
            "scope": "canonical JSON, schema validation, atomic writes, SHA-256 manifest, and read-back",
        },
        "current_proof_consumption": {
            "raw_samples_ms": [round(value, 6) for value in consumption_samples],
            "summary": _summary(consumption_samples),
            "source_digest_match": all(source_matches),
            "expected_source_digest": expected_source_digest,
            "scope": "recompute scoped source tree, checksum read-back, schema validation, parse, and mandatory-count check",
            "known_gap": "Current artifacts do not prove candidate Git SHA, outer ordered gate, run identity, or supersession.",
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
