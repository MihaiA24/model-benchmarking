from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verification import publisher  # noqa: E402
from verification.policy import PolicyError, load_policy  # noqa: E402
from verification.proof import ProofError, consume_proof  # noqa: E402
from verification.publisher import (  # noqa: E402
    PublicationError,
    fail_proof,
    finalize_proof,
    prepare_proof,
    revoke_proof,
)


SCHEMA = ROOT / "verification/proof-envelope-v1.schema.json"
GENERATION = "123e4567-e89b-12d3-a456-426614174000"
OTHER_GENERATION = "223e4567-e89b-12d3-a456-426614174000"


class FakeGitHub:
    def __init__(self, policy: SimpleNamespace, candidate_sha: str) -> None:
        self.policy = policy
        self.candidate_sha = candidate_sha
        self.checks: list[dict[str, object]] = []
        self.artifacts: dict[int, dict[str, object]] = {}
        self.archives: dict[int, bytes] = {}
        self.next_check_id = 99

    def post(
        self,
        repository: str,
        path: str,
        value: dict[str, object],
    ) -> object:
        assert repository == self.policy.repository
        assert path == "/check-runs"
        check = {
            **value,
            "app": {"slug": "github-actions"},
            "conclusion": value.get("conclusion"),
            "head_sha": value["head_sha"],
            "id": self.next_check_id,
        }
        self.next_check_id += 1
        self.checks.append(check)
        return dict(check)

    def patch(
        self,
        repository: str,
        path: str,
        value: dict[str, object],
    ) -> object:
        assert repository == self.policy.repository
        check_id = int(path.rsplit("/", 1)[1])
        check = next(item for item in self.checks if item["id"] == check_id)
        check.update(value)
        return dict(check)

    def get(self, repository: str, path: str) -> object:
        assert repository == self.policy.repository
        if path.startswith("/check-runs/"):
            check_id = int(path.rsplit("/", 1)[1])
            return dict(next(item for item in self.checks if item["id"] == check_id))
        if "/check-runs?" in path:
            return {"check_runs": [dict(item) for item in self.checks]}
        if path == "/actions/runs/10":
            return {
                "id": 10,
                "conclusion": "success",
                "head_sha": self.candidate_sha,
                "path": ".github/workflows/qualification.yml",
                "run_attempt": 1,
                "status": "completed",
            }
        if path.startswith("/actions/artifacts/"):
            artifact_id = int(path.rsplit("/", 1)[1])
            return dict(self.artifacts[artifact_id])
        raise AssertionError(path)

    def download(self, repository: str, path: str) -> bytes:
        assert repository == self.policy.repository
        artifact_id = int(path.split("/")[-2])
        return self.archives[artifact_id]

    def upload(self, state: object, artifact_id: int = 20) -> str:
        bundle_path = Path(getattr(state, "bundle_path"))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
            for path in sorted(bundle_path.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle_path).as_posix())
        data = stream.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        self.archives[artifact_id] = data
        self.artifacts[artifact_id] = {
            "digest": f"sha256:{digest}",
            "expired": False,
            "id": artifact_id,
            "name": getattr(state, "artifact_name"),
            "workflow_run": {"head_sha": self.candidate_sha, "id": 10},
        }
        return digest


def test_publish_read_back_consume_and_revoke_exact_current_proof(tmp_path: Path) -> None:
    repository, policy, head = _repository(tmp_path)
    api = FakeGitHub(policy, head)
    publications = tmp_path / "publications"
    other = publications / OTHER_GENERATION / "sentinel"
    other.parent.mkdir(parents=True)
    other.write_text("keep", encoding="utf-8")
    state_path = tmp_path / "state.json"

    state = _prepare(repository, policy, head, publications, state_path, api)
    digest = api.upload(state)
    pointer = finalize_proof(
        policy=policy,
        schema_path=SCHEMA,
        state_path=state_path,
        artifact_id=20,
        artifact_digest=digest,
        api=api,
    )

    assert pointer.generation_id == GENERATION
    assert other.read_text(encoding="utf-8") == "keep"
    assert not (publications / GENERATION / "execution").exists()
    envelope_path = Path(state.bundle_path) / "proof-envelope.json"
    accepted = consume_proof(
        policy=policy,
        project_root=repository,
        schema_path=SCHEMA,
        envelope_path=envelope_path,
        bundle_root=Path(state.bundle_path),
        api_get=api.get,
    )
    assert accepted["accepted"] is True

    with pytest.raises(PublicationError, match="exact current"):
        revoke_proof(
            policy=policy,
            gate_id="issue-62",
            candidate_sha=head,
            generation_id=OTHER_GENERATION,
            requester="maintainer",
            reason="stale request",
            api=api,
        )
    revocation_id = revoke_proof(
        policy=policy,
        gate_id="issue-62",
        candidate_sha=head,
        generation_id=GENERATION,
        requester="maintainer",
        reason="qualification withdrawn",
        api=api,
    )
    assert revocation_id > pointer.artifact_id
    assert api.checks[-1]["conclusion"] == "failure"
    with pytest.raises(ProofError, match="newest trusted Check Run"):
        consume_proof(
            policy=policy,
            project_root=repository,
            schema_path=SCHEMA,
            envelope_path=envelope_path,
            bundle_root=Path(state.bundle_path),
            api_get=api.get,
        )


@pytest.mark.parametrize("mode", ["failed", "skipped", "timed_out"])
def test_failed_or_incomplete_command_leaves_no_current_success(
    tmp_path: Path,
    mode: str,
) -> None:
    repository, policy, head = _repository(tmp_path, mode=mode)
    api = FakeGitHub(policy, head)
    state_path = tmp_path / "state.json"

    with pytest.raises(PublicationError):
        _prepare(repository, policy, head, tmp_path / "publications", state_path, api)

    assert len(api.checks) == 1
    assert api.checks[0]["conclusion"] == "failure"
    assert not state_path.exists()


@pytest.mark.parametrize("fault", ["rename", "cleanup"])
def test_publication_or_cleanup_fault_never_completes_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    repository, policy, head = _repository(tmp_path)
    api = FakeGitHub(policy, head)
    if fault == "rename":
        original_replace = publisher.os.replace

        def fail_publish(source: object, destination: object) -> None:
            if Path(source).name == "staging":
                raise OSError("seeded rename fault")
            original_replace(source, destination)

        monkeypatch.setattr(publisher.os, "replace", fail_publish)
    else:
        original_cleanup = publisher._remove_worktree

        def fail_cleanup(project_root: Path, execution_root: Path) -> None:
            original_cleanup(project_root, execution_root)
            raise PublicationError("seeded cleanup fault")

        monkeypatch.setattr(publisher, "_remove_worktree", fail_cleanup)

    with pytest.raises(PublicationError):
        _prepare(
            repository,
            policy,
            head,
            tmp_path / "publications",
            tmp_path / "state.json",
            api,
        )

    assert api.checks[-1]["conclusion"] == "failure"


def test_upload_digest_fault_and_explicit_upload_failure_fail_closed(
    tmp_path: Path,
) -> None:
    repository, policy, head = _repository(tmp_path)
    api = FakeGitHub(policy, head)
    state_path = tmp_path / "state.json"
    state = _prepare(
        repository,
        policy,
        head,
        tmp_path / "publications",
        state_path,
        api,
    )
    digest = api.upload(state)
    api.archives[20] += b"tampered"

    with pytest.raises(PublicationError, match="digest read-back"):
        finalize_proof(
            policy=policy,
            schema_path=SCHEMA,
            state_path=state_path,
            artifact_id=20,
            artifact_digest=digest,
            api=api,
        )
    assert api.checks[-1]["conclusion"] == "failure"

    repository_two, policy_two, head_two = _repository(tmp_path / "second")
    api_two = FakeGitHub(policy_two, head_two)
    second_state_path = tmp_path / "second-state.json"
    _prepare(
        repository_two,
        policy_two,
        head_two,
        tmp_path / "second-publications",
        second_state_path,
        api_two,
    )
    fail_proof(
        policy=policy_two,
        state_path=second_state_path,
        reason="official upload action failed",
        api=api_two,
    )
    assert api_two.checks[-1]["conclusion"] == "failure"


def test_worker_authorization_failure_is_published(
    tmp_path: Path,
) -> None:
    repository, policy, head = _repository(tmp_path)
    api = FakeGitHub(policy, head)

    with pytest.raises(PublicationError, match="worker class is not authorized"):
        _prepare(
            repository,
            policy,
            head,
            tmp_path / "publications",
            tmp_path / "state.json",
            api,
            worker_class="untrusted",
        )

    assert len(api.checks) == 1
    assert api.checks[0]["conclusion"] == "failure"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [("head", "fixed candidate HEAD"), ("tracked", "undeclared tracked paths")],
)
def test_fresh_command_cannot_change_candidate_inputs(
    tmp_path: Path, mutation: str, message: str
) -> None:
    repository, policy, head = _repository(tmp_path)
    api = FakeGitHub(policy, head)
    command = policy.fresh_gates["issue-62"]["commands"][0]
    command.update(
        {
            "acceptance_artifact": None,
            "artifacts": [],
            "case_inventory": "none",
            "command": (
                "git commit --allow-empty -m altered"
                if mutation == "head"
                else f"{sys.executable} -c "
                + json.dumps(
                    "from pathlib import Path; Path('emit.py').write_text('changed')"
                )
            ),
        }
    )

    with pytest.raises(PublicationError, match=message):
        _prepare(
            repository,
            policy,
            head,
            tmp_path / "publications",
            tmp_path / "state.json",
            api,
        )

    assert api.checks[-1]["conclusion"] == "failure"


def test_finalize_rejects_wrong_workflow_run_identity(tmp_path: Path) -> None:
    repository, policy, head = _repository(tmp_path)
    api = FakeGitHub(policy, head)
    state_path = tmp_path / "state.json"
    state = _prepare(
        repository, policy, head, tmp_path / "publications", state_path, api
    )
    digest = api.upload(state)
    api.candidate_sha = "b" * 40

    with pytest.raises(PublicationError, match="workflow run identity"):
        finalize_proof(
            policy=policy,
            schema_path=SCHEMA,
            state_path=state_path,
            artifact_id=20,
            artifact_digest=digest,
            api=api,
        )

    assert api.checks[-1]["conclusion"] == "failure"


def test_policy_requires_explicit_acceptance_inventory_and_timeout(
    tmp_path: Path,
) -> None:
    value = json.loads((ROOT / "verification/policy.json").read_text(encoding="utf-8"))
    command = value["fresh_gates"][1]["commands"][1]
    command["artifacts"] = [command["acceptance_artifact"]]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(PolicyError, match="inventory is incomplete"):
        load_policy(path)

    command["artifacts"].append("artifacts/acceptance/issue-28/sha256sums.txt")
    command["timeout_seconds"] = 0
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PolicyError, match="timeout_seconds"):
        load_policy(path)


def _prepare(
    repository: Path,
    policy: SimpleNamespace,
    head: str,
    publications: Path,
    state_path: Path,
    api: FakeGitHub,
    *,
    worker_class: str = "dedicated-ci",
) -> object:
    return prepare_proof(
        policy=policy,
        project_root=repository,
        schema_path=SCHEMA,
        publication_root=publications,
        state_path=state_path,
        gate_id="issue-62",
        candidate_sha=head,
        run_id=10,
        run_attempt=1,
        requester="verification-test",
        reason="fixed-head qualification",
        worker_class=worker_class,
        worker_identity="test-runner",
        docker_daemon=None,
        api=api,
        generation_id=GENERATION,
    )


def _repository(
    tmp_path: Path,
    *,
    mode: str = "passed",
) -> tuple[Path, SimpleNamespace, str]:
    repository = tmp_path / "repository"
    repository.mkdir(parents=True)
    artifact_path = "artifacts/acceptance/issue-62/verification.json"
    manifest_path = "artifacts/acceptance/issue-62/sha256sums.txt"
    if mode == "timed_out":
        command = f'{sys.executable} -c "import time; time.sleep(2)"'
        case_inventory = "none"
        acceptance_artifact = None
        artifacts: list[str] = []
        timeout = 1
    else:
        outcome = "skipped" if mode == "skipped" else "passed"
        exit_code = 7 if mode == "failed" else 0
        (repository / "emit.py").write_text(
            _emitter(outcome=outcome, exit_code=exit_code),
            encoding="utf-8",
        )
        command = f"{sys.executable} emit.py"
        case_inventory = "required"
        acceptance_artifact = artifact_path
        artifacts = [artifact_path, manifest_path]
        timeout = 30

    stale = repository / artifact_path
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    (repository / manifest_path).write_text("stale", encoding="utf-8")
    _git(repository, "init")
    _git(repository, "config", "user.email", "verification@example.invalid")
    _git(repository, "config", "user.name", "Verification Test")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "fixture")
    head = _git(repository, "rev-parse", "HEAD").strip()
    gate = {
        "check_name": "qualification / issue-62",
        "commands": [
            {
                "acceptance_artifact": acceptance_artifact,
                "artifacts": artifacts,
                "case_inventory": case_inventory,
                "command": command,
                "id": "acceptance",
                "timeout_seconds": timeout,
            }
        ],
        "docker_required": False,
        "id": "issue-62",
        "trusted_app_slug": "github-actions",
        "worker_classes": ["dedicated-ci"],
        "workflow_path": ".github/workflows/qualification.yml",
    }
    policy = SimpleNamespace(
        fresh_gates={"issue-62": gate},
        repository="MihaiA24/model-benchmarking",
        sha256="a" * 64,
    )
    return repository, policy, head


def _emitter(*, outcome: str, exit_code: int) -> str:
    return f'''import hashlib
import json
from pathlib import Path

root = Path("artifacts/acceptance/issue-62")
root.mkdir(parents=True, exist_ok=True)
path = root / "verification.json"
value = {{
    "case_results": [{{"id": "mandatory", "outcome": "{outcome}"}}],
    "command": "fixture",
    "input_identities": {{}},
    "issue": 62,
    "output_paths": [],
    "schema": {{"name": "model-benchmark/verification-artifact"}},
}}
data = json.dumps(value, sort_keys=True).encode("utf-8")
path.write_bytes(data)
digest = hashlib.sha256(data).hexdigest()
(root / "sha256sums.txt").write_text(
    f"{{digest}}  artifacts/acceptance/issue-62/verification.json\\n",
    encoding="utf-8",
)
raise SystemExit({exit_code})
'''


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
