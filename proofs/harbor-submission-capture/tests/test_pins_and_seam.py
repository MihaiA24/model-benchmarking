from __future__ import annotations

import tomllib  # type: ignore[import-not-found]
from pathlib import Path


PROOF_ROOT = Path(__file__).resolve().parents[1]
HARBOR_COMMIT = "527d50deb63a5d279e8c20593c18a2cbc7f61f9e"
HARBOR_DEPENDENCY = (
    "harbor @ git+https://github.com/harbor-framework/harbor.git@" + HARBOR_COMMIT
)
BASE_IMAGE = (
    "python:3.12.12-slim-bookworm@"
    "sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
)


def test_harbor_and_docker_inputs_are_immutable() -> None:
    project = tomllib.loads((PROOF_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert HARBOR_DEPENDENCY in project["project"]["dependencies"]

    lock = (PROOF_ROOT / "uv.lock").read_text(encoding="utf-8")
    locked_source = (
        "https://github.com/harbor-framework/harbor.git?rev="
        f"{HARBOR_COMMIT}#{HARBOR_COMMIT}"
    )
    assert locked_source in lock

    dockerfiles = [
        PROOF_ROOT / "fixtures/task/environment/Dockerfile",
        PROOF_ROOT / "fixtures/task/environment/capture/Dockerfile",
        PROOF_ROOT / "fixtures/task/tests/Dockerfile",
    ]
    for dockerfile in dockerfiles:
        first_line = dockerfile.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == f"FROM {BASE_IMAGE}"


def test_task_uses_only_supported_public_harbor_seams() -> None:
    task_path = PROOF_ROOT / "fixtures/task/task.toml"
    task = tomllib.loads(task_path.read_text(encoding="utf-8"))
    assert task["verifier"]["environment_mode"] == "separate"
    assert task["verifier"]["collect"] == [
        {
            "service": "capture",
            "command": "python3 /opt/capture/capture.py --repository /input/repo --baseline /opt/capture/baseline --policy /opt/capture/policy.json --output /capture",
            "timeout_sec": 30.0,
        }
    ]
    assert {entry["service"] for entry in task["artifacts"]} == {"capture"}
    assert {entry["source"] for entry in task["artifacts"]} == {
        "/capture/capture.json",
        "/capture/submission.patch",
    }

    compose = (
        PROOF_ROOT / "fixtures/task/environment/docker-compose.yaml"
    ).read_text(encoding="utf-8")
    assert "trial-repository:/input:ro" in compose
    assert "trial-repository:/workspace" in compose
    assert "network_mode: none" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose

    collector = (
        PROOF_ROOT / "fixtures/task/environment/capture/capture.py"
    ).read_text(encoding="utf-8")
    assert "import harbor" not in collector
    assert "from harbor" not in collector
