from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verification.policy import Policy, load_policy  # noqa: E402
from verification.proof import (  # noqa: E402
    ProofError,
    ProofPointer,
    consume_proof,
    encode_pointer,
    source_tree_sha256,
)
POLICY_PATH = ROOT / "verification/policy.json"
SCHEMA_PATH = ROOT / "verification/proof-envelope-v1.schema.json"


class FakeGitHub:
    def __init__(self, *, policy: Policy, envelope: dict[str, object], envelope_sha256: str) -> None:
        self.policy = policy
        self.envelope = envelope
        self.gate = policy.fresh_gates[str(envelope["gate_id"])]
        workflow = envelope["workflow"]
        assert isinstance(workflow, dict)
        self.pointer = encode_pointer(
            ProofPointer(
                gate_id=str(envelope["gate_id"]),
                policy_sha256=policy.sha256,
                run_id=int(workflow["run_id"]),
                run_attempt=int(workflow["run_attempt"]),
                generation_id=str(envelope["generation_id"]),
                envelope_sha256=envelope_sha256,
                artifact_id=20,
            )
        )
        self.check_runs: list[dict[str, object]] = [self._check(99)]
        self.run: dict[str, object] = {
            "conclusion": "success",
            "head_sha": envelope["candidate_sha"],
            "path": self.gate["workflow_path"],
            "run_attempt": workflow["run_attempt"],
            "status": "completed",
        }
        self.artifact: dict[str, object] = {
            "expired": False,
            "workflow_run": {
                "head_sha": envelope["candidate_sha"],
                "id": workflow["run_id"],
            },
        }

    def _check(
        self,
        check_id: int,
        *,
        status: str = "completed",
        conclusion: str | None = "success",
        pointer: str | None = None,
    ) -> dict[str, object]:
        return {
            "app": {"slug": self.gate["trusted_app_slug"]},
            "conclusion": conclusion,
            "external_id": self.pointer if pointer is None else pointer,
            "id": check_id,
            "name": self.gate["check_name"],
            "status": status,
        }

    def get(self, repository: str, path: str) -> object:
        assert repository == self.policy.repository
        if "/check-runs?" in path:
            return {"check_runs": self.check_runs}
        if path == "/actions/runs/10":
            return self.run
        if path == "/actions/artifacts/20":
            return self.artifact
        raise AssertionError(path)


def test_exact_matching_live_current_proof_is_accepted(tmp_path: Path) -> None:
    policy, envelope, envelope_path, bundle_root = _proof(tmp_path)
    api = FakeGitHub(
        policy=policy,
        envelope=envelope,
        envelope_sha256=_digest(envelope_path),
    )

    result = _consume(policy, envelope_path, bundle_root, api.get)

    assert result["accepted"] is True
    assert result["authority"] == "fresh_authoritative"
    assert result["candidate_sha"] == _head()
    assert result["diagnostics"] == {
        "child_artifact_count": 2,
        "command_count": 4,
        "shape": "proof-consumption-diagnostics-v1",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "authority",
        "candidate",
        "policy",
        "schema",
        "source",
        "ordered-command",
        "missing-case",
        "failed-case",
        "worker",
        "child-checksum",
        "missing-field",
    ],
)
def test_envelope_identity_and_completeness_drift_is_rejected(
    tmp_path: Path,
    mutation: str,
) -> None:
    policy, envelope, envelope_path, bundle_root = _proof(tmp_path)
    _mutate(envelope, mutation)
    envelope_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    api_get: Callable[[str, str], object]
    if mutation == "missing-field":
        def empty_api(_repository: str, _path: str) -> object:
            return {}

        api_get = empty_api
    else:
        api_get = FakeGitHub(
            policy=policy,
            envelope=envelope,
            envelope_sha256=_digest(envelope_path),
        ).get

    with pytest.raises(ProofError):
        _consume(policy, envelope_path, bundle_root, api_get)


def test_legacy_child_artifact_cannot_be_consumed_as_outer_proof(tmp_path: Path) -> None:
    policy, _, _, bundle_root = _proof(tmp_path)
    legacy = bundle_root / "artifacts/acceptance/issue-28/verification.json"

    with pytest.raises(ProofError):
        _consume(policy, legacy, bundle_root, lambda _repository, _path: {})


def test_newest_trusted_attempt_supersedes_older_success_regardless_of_status(
    tmp_path: Path,
) -> None:
    policy, envelope, envelope_path, bundle_root = _proof(tmp_path)
    api = FakeGitHub(
        policy=policy,
        envelope=envelope,
        envelope_sha256=_digest(envelope_path),
    )
    api.check_runs = [
        api._check(98),
        api._check(100, status="in_progress", conclusion=None, pointer="malformed"),
    ]

    with pytest.raises(ProofError, match="newest trusted Check Run"):
        _consume(policy, envelope_path, bundle_root, api.get)


@pytest.mark.parametrize(
    "state,conclusion",
    [
        ("queued", None),
        ("in_progress", None),
        ("completed", "failure"),
        ("completed", "cancelled"),
    ],
)
def test_non_successful_current_attempt_is_rejected(
    tmp_path: Path,
    state: str,
    conclusion: str | None,
) -> None:
    policy, envelope, envelope_path, bundle_root = _proof(tmp_path)
    api = FakeGitHub(
        policy=policy,
        envelope=envelope,
        envelope_sha256=_digest(envelope_path),
    )
    api.check_runs = [api._check(99, status=state, conclusion=conclusion)]

    with pytest.raises(ProofError):
        _consume(policy, envelope_path, bundle_root, api.get)


def test_successful_replacement_with_another_generation_revokes_old_proof(
    tmp_path: Path,
) -> None:
    policy, envelope, envelope_path, bundle_root = _proof(tmp_path)
    api = FakeGitHub(
        policy=policy,
        envelope=envelope,
        envelope_sha256=_digest(envelope_path),
    )
    replacement = api.pointer.replace(
        str(envelope["generation_id"]),
        "223e4567-e89b-12d3-a456-426614174000",
    )
    api.check_runs = [api._check(99), api._check(100, pointer=replacement)]

    with pytest.raises(ProofError, match="does not point to this exact proof"):
        _consume(policy, envelope_path, bundle_root, api.get)


def test_unavailable_currentness_fails_closed(tmp_path: Path) -> None:
    policy, _, envelope_path, bundle_root = _proof(tmp_path)

    def unavailable(_repository: str, _path: str) -> object:
        raise ProofError("unavailable")

    with pytest.raises(ProofError, match="unavailable"):
        _consume(policy, envelope_path, bundle_root, unavailable)


def test_expired_or_mismatched_live_artifact_is_rejected(tmp_path: Path) -> None:
    policy, envelope, envelope_path, bundle_root = _proof(tmp_path)
    api = FakeGitHub(
        policy=policy,
        envelope=envelope,
        envelope_sha256=_digest(envelope_path),
    )
    api.artifact["expired"] = True

    with pytest.raises(ProofError, match="artifact is unavailable"):
        _consume(policy, envelope_path, bundle_root, api.get)


def _proof(
    tmp_path: Path,
) -> tuple[Policy, dict[str, object], Path, Path]:
    policy = load_policy(POLICY_PATH)
    bundle_root = tmp_path / "bundle"
    child_root = bundle_root / "artifacts/acceptance/issue-28"
    child_root.mkdir(parents=True)
    source_root = ROOT / "artifacts/acceptance/issue-28"
    for name in ("verification.json", "sha256sums.txt"):
        shutil.copyfile(source_root / name, child_root / name)
    verification = json.loads((child_root / "verification.json").read_text())
    head = _head()
    gate = policy.fresh_gates["issue-28"]
    commands = gate["commands"]
    assert isinstance(commands, list)
    envelope: dict[str, object] = {
        "authority": "fresh_authoritative",
        "candidate_sha": head,
        "child_artifacts": [
            {
                "path": f"artifacts/acceptance/issue-28/{name}",
                "sha256": _digest(child_root / name),
            }
            for name in ("verification.json", "sha256sums.txt")
        ],
        "commands": [
            {
                "cases": (
                    verification["case_results"]
                    if command["case_inventory"] == "required"
                    else []
                ),
                "command": command["command"],
                "completed_at": "2026-07-15T10:01:00Z",
                "exit_code": 0,
                "id": command["id"],
                "outcome": "passed",
                "started_at": "2026-07-15T10:00:00Z",
            }
            for command in commands
        ],
        "created_at": "2026-07-15T10:02:00Z",
        "gate_id": "issue-28",
        "generation_id": "123e4567-e89b-12d3-a456-426614174000",
        "policy_sha256": policy.sha256,
        "repository": policy.repository,
        "schema_sha256": _digest(SCHEMA_PATH),
        "source_tree_sha256": source_tree_sha256(ROOT, head),
        "version": 1,
        "worker": {
            "class": "local-reference",
            "docker_daemon": None,
            "identity": "test-worker",
            "qualification_state": "qualified",
        },
        "workflow": {
            "check_run_id": 99,
            "path": gate["workflow_path"],
            "reason": "fixed-head review",
            "requester": "verification-test",
            "run_attempt": 1,
            "run_id": 10,
        },
    }
    envelope_path = bundle_root / "proof-envelope.json"
    envelope_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    return policy, envelope, envelope_path, bundle_root


def _mutate(envelope: dict[str, object], mutation: str) -> None:
    if mutation == "authority":
        envelope["authority"] = "diagnostic"
    elif mutation == "candidate":
        envelope["candidate_sha"] = "0" * 40
    elif mutation == "policy":
        envelope["policy_sha256"] = "0" * 64
    elif mutation == "schema":
        envelope["schema_sha256"] = "0" * 64
    elif mutation == "source":
        envelope["source_tree_sha256"] = "0" * 64
    elif mutation == "ordered-command":
        commands = envelope["commands"]
        assert isinstance(commands, list)
        commands[0]["command"] = "uv sync"
    elif mutation == "missing-case":
        commands = envelope["commands"]
        assert isinstance(commands, list)
        commands[1]["cases"] = commands[1]["cases"][1:]
    elif mutation == "failed-case":
        commands = envelope["commands"]
        assert isinstance(commands, list)
        commands[1]["cases"][0]["outcome"] = "failed"
    elif mutation == "worker":
        worker = envelope["worker"]
        assert isinstance(worker, dict)
        worker["class"] = "unqualified-worker"
    elif mutation == "child-checksum":
        artifacts = envelope["child_artifacts"]
        assert isinstance(artifacts, list)
        artifacts[0]["sha256"] = "0" * 64
    elif mutation == "missing-field":
        del envelope["workflow"]
    else:
        raise AssertionError(mutation)


def _consume(
    policy: Policy,
    envelope_path: Path,
    bundle_root: Path,
    api_get: Callable[[str, str], object],
) -> dict[str, object]:
    return consume_proof(
        policy=policy,
        project_root=ROOT,
        schema_path=SCHEMA_PATH,
        envelope_path=envelope_path,
        bundle_root=bundle_root,
        api_get=api_get,
    )


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
