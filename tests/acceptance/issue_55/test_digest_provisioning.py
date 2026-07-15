from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from model_benchmark.runtime.provisioning import (
    DockerTarget,
    acquire_store_lease,
    ensure_locked_images,
    remove_project_images,
)


REGISTRY_IMAGE = (
    "registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
)
SOURCE_IMAGE = (
    "python:3.12.12-slim-bookworm@sha256:"
    "593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
)


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        timeout=600,
        check=check,
    )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_cold_digest_pull_then_warm_inspection_makes_zero_registry_requests(
    tmp_path: Path, acceptance_observation: Callable[[str, object], None]
) -> None:
    _docker("pull", REGISTRY_IMAGE)
    _docker("pull", SOURCE_IMAGE)
    context = _docker("context", "show").stdout.strip()
    platform = (
        _docker("info", "--format", "{{.OSType}}/{{.Architecture}}")
        .stdout.strip()
        .replace("aarch64", "arm64")
        .replace("x86_64", "amd64")
    )
    port = _free_port()
    container = f"model-benchmark-registry-{port}"
    mutable_reference = f"localhost:{port}/controlled/base:seed"
    cleanup_project = "model-benchmark-issue55-failure-cleanup"
    cleanup_reference = "model-benchmark-issue55-cleanup:failure"
    _docker("image", "rm", cleanup_reference, check=False)
    _docker(
        "run",
        "--detach",
        "--name",
        container,
        "--publish",
        f"{port}:5000",
        REGISTRY_IMAGE,
    )
    try:
        _docker("tag", SOURCE_IMAGE, mutable_reference)
        _docker("push", mutable_reference)
        repo_digests = _docker(
            "image", "inspect", mutable_reference, "--format", "{{json .RepoDigests}}"
        ).stdout
        import json

        exact_reference = next(
            value
            for value in json.loads(repo_digests)
            if value.startswith(f"localhost:{port}/controlled/base@sha256:")
        )
        _docker("image", "rm", mutable_reference, check=False)
        _docker("image", "rm", exact_reference, check=False)
        locked = [
            {
                "identity": "oci-image:sha256:" + "1" * 64,
                "reference": exact_reference,
            }
        ]
        target = DockerTarget(context=context, platform=platform)
        with acquire_store_lease(target, visibility="public") as lease:
            cold_since = datetime.now(UTC).isoformat()
            cold = ensure_locked_images(lease, locked)
            cold_logs = _docker("logs", "--since", cold_since, container).stderr
            assert cold[0]["cache"] == "miss"
            assert "/v2/controlled/base/" in cold_logs

            warm_since = datetime.now(UTC).isoformat()
            started = time.monotonic()
            warm = ensure_locked_images(lease, locked)
            elapsed = time.monotonic() - started
            warm_logs = _docker("logs", "--since", warm_since, container).stderr
            assert warm[0]["cache"] == "hit"
            assert elapsed <= 2.0
            registry_request_count = warm_logs.count("/v2/controlled/base/")
            assert registry_request_count == 0

            build = tmp_path / "cleanup-image"
            build.mkdir()
            (build / "Dockerfile").write_text(
                f"FROM {SOURCE_IMAGE}\n", encoding="utf-8"
            )
            _docker(
                "build",
                "--tag",
                cleanup_reference,
                "--label",
                f"com.docker.compose.project={cleanup_project}",
                str(build),
            )
            assert (
                _docker("image", "inspect", cleanup_reference, check=False).returncode
                == 0
            )
            remove_project_images(lease, {cleanup_project})
            assert (
                _docker("image", "inspect", cleanup_reference, check=False).returncode
                != 0
            )

            acceptance_observation(
                "registry-request-count-0", {"count": registry_request_count}
            )
            acceptance_observation(
                "cold-cache-miss-image-identity",
                {"image_id": cold[0]["image"]["id"]},
            )
            acceptance_observation(
                "warm-cache-hit-image-identity",
                {"image_id": warm[0]["image"]["id"]},
            )
            acceptance_observation(
                "failure-cleanup-complete", {"mutable_project_images": 0}
            )
    finally:
        _docker("image", "rm", cleanup_reference, check=False)
        _docker("image", "rm", mutable_reference, check=False)
        _docker("rm", "--force", container, check=False)
