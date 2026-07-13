from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROOF_ROOT = Path(__file__).resolve().parents[1]
TASK_TEMPLATE = PROOF_ROOT / "fixtures" / "task"
NORMAL_SOLUTION = """#!/bin/sh
set -eu
printf 'after\\n' > src/app.txt
printf 'new\\n' > src/new.txt
mkdir -p /workspace/agent-home/cache
printf 'must-not-cross\\n' > /workspace/agent-home/cache/secret.txt
"""


def _run_case(
    tmp_path: Path,
    *,
    name: str,
    solution: str,
    expected: dict[str, str],
    collect_command: str | None = None,
) -> dict[str, object]:
    task_dir = tmp_path / "task"
    trials_dir = tmp_path / "trials"
    shutil.copytree(TASK_TEMPLATE, task_dir)
    harness_guard = "test ! -e /tests\ntest ! -e /capture\n"
    assert "set -eu\n" in solution
    solution = solution.replace("set -eu\n", f"set -eu\n{harness_guard}", 1)
    (task_dir / "solution" / "solve.sh").write_text(solution, encoding="utf-8")
    (task_dir / "tests" / "expected.json").write_text(
        json.dumps(expected, sort_keys=True),
        encoding="utf-8",
    )
    if collect_command is not None:
        task_config = task_dir / "task.toml"
        config_text = task_config.read_text(encoding="utf-8")
        original = "python3 /opt/capture/capture.py --repository /input/repo --baseline /opt/capture/baseline --policy /opt/capture/policy.json --output /capture"
        assert original in config_text
        task_config.write_text(
            config_text.replace(original, collect_command),
            encoding="utf-8",
        )

    harbor = shutil.which("harbor")
    assert harbor is not None, "Harbor must resolve from the frozen proof environment"
    completed = subprocess.run(
        [
            harbor,
            "trial",
            "start",
            "--path",
            str(task_dir),
            "--agent",
            "oracle",
            "--trial-name",
            name,
            "--trials-dir",
            str(trials_dir),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    trial_dirs = sorted(path for path in trials_dir.iterdir() if path.is_dir())
    assert len(trial_dirs) == 1, trial_dirs
    trial_dir = trial_dirs[0]
    result = json.loads((trial_dir / "result.json").read_text(encoding="utf-8"))
    trial_log = (trial_dir / "trial.log").read_text(encoding="utf-8")
    stopped = trial_log.index("Main service stopped")
    collected = trial_log.index("Running collect hook in service 'capture'")
    assert stopped < collected

    artifact_dir = trial_dir / "artifacts" / "capture"
    capture_path = artifact_dir / "capture.json"
    patch_path = artifact_dir / "submission.patch"
    return {
        "artifact_dir": artifact_dir,
        "manifest": json.loads(
            (trial_dir / "artifacts" / "manifest.json").read_text(encoding="utf-8")
        ),
        "patch": patch_path.read_bytes() if patch_path.exists() else None,
        "record": (
            json.loads(capture_path.read_text(encoding="utf-8"))
            if capture_path.exists()
            else None
        ),
        "result": result,
        "trial_dir": trial_dir,
    }


def test_normal_patch_uses_post_stop_sidecar_and_separate_verifier(tmp_path: Path) -> None:
    """Only the sidecar-derived handoff reaches a fresh verifier after main stops."""
    docker = shutil.which("docker")
    assert docker is not None, "Docker is required; this proof must not skip"
    daemon = subprocess.run(
        [docker, "info"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert daemon.returncode == 0, daemon.stderr or daemon.stdout
    assert TASK_TEMPLATE.is_dir(), f"missing proof task fixture: {TASK_TEMPLATE}"

    outcome = _run_case(
        tmp_path,
        name="normal-patch",
        solution=NORMAL_SOLUTION,
        expected={"case": "normal-patch", "kind": "patch", "status": "accepted"},
    )
    result = outcome["result"]
    assert isinstance(result, dict)
    assert result["exception_info"] is None, result["exception_info"]
    assert result["verifier_result"]["rewards"]["reward"] == 1
    record = outcome["record"]
    patch = outcome["patch"]
    assert isinstance(record, dict)
    assert isinstance(patch, bytes)
    assert record["status"] == "accepted"
    assert record["kind"] == "patch"
    assert record["patch_sha256"] == hashlib.sha256(patch).hexdigest()
    assert b"must-not-cross" not in patch


def test_noop_is_an_explicit_accepted_submission(tmp_path: Path) -> None:
    outcome = _run_case(
        tmp_path,
        name="no-op",
        solution="#!/bin/sh\nset -eu\n",
        expected={"case": "no-op", "kind": "no-op", "status": "accepted"},
    )
    result = outcome["result"]
    record = outcome["record"]
    assert isinstance(result, dict)
    assert isinstance(record, dict)
    assert result["exception_info"] is None
    assert result["verifier_result"]["rewards"]["reward"] == 1
    assert record["status"] == "accepted"
    assert record["kind"] == "no-op"
    assert outcome["patch"] == b""


@pytest.mark.parametrize(
    ("name", "solution", "reason"),
    [
        (
            "malicious-path",
            "#!/bin/sh\nset -eu\nprintf 'escape\\n' > undeclared-secret.txt\n",
            "undeclared_path",
        ),
        (
            "symlink",
            "#!/bin/sh\nset -eu\nln -s /etc/passwd src/escape-link\n",
            "symlink",
        ),
        (
            "special-file",
            "#!/bin/sh\nset -eu\nmkfifo src/agent-pipe\n",
            "special_file",
        ),
        (
            "oversized",
            "#!/bin/sh\nset -eu\npython3 -c \"from pathlib import Path; Path('src/large.txt').write_text('x' * 2048)\"\n",
            "byte_limit",
        ),
    ],
    ids=["malicious-path", "symlink", "special-file", "oversized"],
)
def test_unsafe_repository_state_is_rejected_without_partial_submission(
    tmp_path: Path,
    name: str,
    solution: str,
    reason: str,
) -> None:
    outcome = _run_case(
        tmp_path,
        name=name,
        solution=solution,
        expected={"case": name, "reason": reason, "status": "rejected"},
    )
    result = outcome["result"]
    record = outcome["record"]
    manifest = outcome["manifest"]
    assert isinstance(result, dict)
    assert isinstance(record, dict)
    assert isinstance(manifest, list)
    assert result["exception_info"] is None
    assert result["verifier_result"]["rewards"]["reward"] == 0
    assert record["status"] == "rejected"
    assert record["reason"] == reason
    assert outcome["patch"] is None

    statuses = {entry["source"]: entry["status"] for entry in manifest}
    assert statuses["/capture/capture.json"] == "ok"
    assert statuses["/capture/submission.patch"] == "failed"


def test_racing_descendant_is_stopped_before_stable_capture(tmp_path: Path) -> None:
    solution = """#!/bin/sh
set -eu
printf 'started\\n' > src/race.txt
nohup sh -c 'while :; do printf "x\\n" >> /workspace/repo/src/race.txt; sleep 0.1; done' >/dev/null 2>&1 </dev/null &
printf '%s\\n' "$!" > src/descendant.pid
"""
    outcome = _run_case(
        tmp_path,
        name="racing-descendant",
        solution=solution,
        expected={
            "case": "racing-descendant",
            "kind": "patch",
            "status": "accepted",
        },
    )
    result = outcome["result"]
    record = outcome["record"]
    patch = outcome["patch"]
    assert isinstance(result, dict)
    assert isinstance(record, dict)
    assert isinstance(patch, bytes)
    assert result["exception_info"] is None
    assert result["verifier_result"]["rewards"]["reward"] == 1
    assert record["status"] == "accepted"
    assert record["stability_window_ms"] == 250
    assert b"src/race.txt" in patch
    assert b"src/descendant.pid" in patch


def test_missing_capture_never_becomes_an_authoritative_submission(tmp_path: Path) -> None:
    outcome = _run_case(
        tmp_path,
        name="missing-capture",
        solution=NORMAL_SOLUTION,
        expected={"case": "missing-capture", "status": "missing"},
        collect_command="rm -f /capture/capture.json /capture/submission.patch",
    )
    result = outcome["result"]
    manifest = outcome["manifest"]
    assert isinstance(result, dict)
    assert isinstance(manifest, list)
    assert result["exception_info"] is None
    assert result["verifier_result"]["rewards"]["reward"] == 0
    assert outcome["record"] is None
    assert outcome["patch"] is None

    statuses = {entry["source"]: entry["status"] for entry in manifest}
    assert statuses["/capture/capture.json"] == "failed"
    assert statuses["/capture/submission.patch"] == "failed"
