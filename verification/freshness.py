"""Fail-closed Acceptance Artifact Freshness checks.

The acceptance plugin (``model_benchmark.evidence.pytest_acceptance``)
publishes each Acceptance Verification Artifact under
``artifacts/acceptance/issue-N/`` with the digests of its Acceptance Source
Tree. Nothing in the development gate re-executes acceptance suites, so a
runtime change that skips the reseal ritual leaves stale Acceptance
Verification Artifacts behind silently. This module recomputes each recomputable
input against the working tree and fails closed on drift without running tests.

It deliberately reuses the plugin's own closure builder instead of
duplicating the path list: the checker must never disagree with the
producer about what an Acceptance Verification Artifact covers. The plugin
lives inside the sealed runtime tree, so widening its public surface for a
consumer would force a condition-lock reseal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from model_benchmark.evidence.pytest_acceptance import (
    _ISSUE_DIRECTORY,
    _AcceptanceState,
    _verification_inputs,
)
from model_benchmark.evidence.verification import (
    VerificationArtifactError,
    verify_checksum_manifest,
)


RECOMPUTABLE_INPUTS = (
    "acceptance-source-tree",
    "canonicalization-contract",
    "pyproject.toml",
    "schema-catalog",
    "uv.lock",
)


class FreshnessError(RuntimeError):
    """The acceptance layout cannot be checked coherently."""


@dataclass(frozen=True)
class ProofFreshness:
    issue: int
    directory: str
    status: str
    detail: str = ""
    stale_inputs: tuple[str, ...] = ()
    not_recomputable: tuple[str, ...] = ()

    @property
    def fresh(self) -> bool:
        return self.status == "fresh"


def acceptance_directories(project_root: Path) -> dict[int, Path]:
    root = project_root / "tests/acceptance"
    directories: dict[int, Path] = {}
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        match = _ISSUE_DIRECTORY.fullmatch(candidate.name)
        if match is None:
            continue
        issue = int(match.group(1))
        claimed = directories.get(issue)
        if claimed is not None:
            raise FreshnessError(
                f"issue {issue} is claimed by both {claimed.name} and {candidate.name}"
            )
        directories[issue] = candidate
    if not directories:
        raise FreshnessError(f"no acceptance suite directories under {root}")
    return directories


def _recomputed_inputs(
    project_root: Path,
    issue: int,
    issue_path: Path,
    input_paths: Sequence[str],
) -> dict[str, str]:
    state = _AcceptanceState(
        project_root=project_root,
        issue_path=issue_path,
        issue=issue,
    )
    for relative in input_paths:
        state.input_paths.append((project_root / relative).resolve())
    return {entry.name: str(entry.digest) for entry in _verification_inputs(state)}


def check_acceptance_proofs(
    project_root: Path,
    input_paths_by_issue: Mapping[int, Sequence[str]] | None = None,
) -> list[ProofFreshness]:
    """Report per-suite Acceptance Artifact Freshness; drift is fail-closed.

    ``input_paths_by_issue`` mirrors each suite's ``--acceptance-input``
    launch arguments (project-relative paths); suites absent from the
    mapping recompute over the base closure only. Sealed inputs the
    checker cannot recompute (launcher identities, Docker versions, live
    attestations, per-case observations) are reported, never trusted as
    freshness evidence and never treated as drift.
    """
    extras = dict(input_paths_by_issue or {})
    reports: list[ProofFreshness] = []
    for issue, issue_path in acceptance_directories(project_root).items():
        directory = issue_path.name
        artifact_root = project_root / f"artifacts/acceptance/issue-{issue}"
        verification = artifact_root / "verification.json"
        manifest = artifact_root / "sha256sums.txt"
        if not verification.is_file() or not manifest.is_file():
            reports.append(
                ProofFreshness(
                    issue,
                    directory,
                    "missing",
                    detail="verification.json or sha256sums.txt is absent",
                )
            )
            continue
        try:
            verify_checksum_manifest(project_root, manifest)
        except VerificationArtifactError as error:
            reports.append(
                ProofFreshness(issue, directory, "tampered", detail=str(error))
            )
            continue
        try:
            document = json.loads(verification.read_bytes())
            identities = {
                str(entry["name"]): str(entry["digest"])
                for entry in document["input_identities"]
            }
        except (KeyError, TypeError, ValueError) as error:
            reports.append(
                ProofFreshness(
                    issue,
                    directory,
                    "tampered",
                    detail=f"verification.json is malformed: {error}",
                )
            )
            continue
        recomputed = _recomputed_inputs(
            project_root, issue, issue_path, extras.get(issue, ())
        )
        stale = tuple(
            name
            for name in RECOMPUTABLE_INPUTS
            if identities.get(name) != recomputed[name]
        )
        reports.append(
            ProofFreshness(
                issue,
                directory,
                "stale" if stale else "fresh",
                stale_inputs=stale,
                not_recomputable=tuple(
                    sorted(set(identities) - set(RECOMPUTABLE_INPUTS))
                ),
            )
        )
    return reports
