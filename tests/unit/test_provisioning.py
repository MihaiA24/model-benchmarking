from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from model_benchmark.declarations.scenarios import ScenarioPackageError
from model_benchmark.runtime import provisioning
from model_benchmark.runtime.provisioning import (
    DockerTarget,
    StoreLease,
    ensure_locked_images,
    load_target_config,
    preflight,
)
from model_benchmark.runtime.scenario_qualification import provision_scenario_package


def _image(reference: str) -> dict[str, object]:
    return {
        "Architecture": "amd64",
        "Config": {"Labels": {}},
        "Id": "sha256:" + "1" * 64,
        "Os": "linux",
        "RepoDigests": [provisioning._canonical_repo_digest(reference)],
        "RootFS": {"Layers": ["sha256:" + "2" * 64]},
        "Variant": "",
    }


def _sealed_image(reference: str) -> dict[str, object]:
    image: dict[str, object] = {
        "architecture": "amd64",
        "id": "sha256:" + "1" * 64,
        "layers": ["sha256:" + "2" * 64],
        "os": "linux",
        "repo_digests": [provisioning._canonical_repo_digest(reference)],
        "variant": None,
    }
    image["content_identity"] = provisioning._artifact_digest(image)
    return image


def _lease() -> StoreLease:
    return StoreLease(
        target=DockerTarget(context="public-cache", platform="linux/amd64"),
        visibility_domain="public",
        store={
            "docker_context": "public-cache",
            "platform": "linux/amd64",
            "server_version": "29.0.0",
            "store_identity": "artifact:sha256:" + "3" * 64,
        },
    )


def test_warm_digest_hit_uses_only_exact_local_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = "registry.example/repository@sha256:" + "4" * 64
    calls: list[list[str]] = []
    contexts: list[str | None] = []

    def fake_docker(
        arguments: list[str],
        *,
        timeout: int = 30,
        check: bool = True,
        context: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        contexts.append(context)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps([_image(reference)]),
            stderr="",
        )

    monkeypatch.setattr(provisioning, "_docker", fake_docker)

    records = ensure_locked_images(
        _lease(),
        [{"identity": "oci-image:sha256:" + "5" * 64, "reference": reference}],
    )

    assert records[0]["cache"] == "hit"
    assert calls == [["image", "inspect", reference]]
    assert contexts == ["public-cache"]


def test_cold_digest_miss_pulls_once_then_seals_selected_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = "registry.example/repository@sha256:" + "4" * 64
    calls: list[list[str]] = []
    inspections = 0

    def fake_docker(
        arguments: list[str],
        *,
        timeout: int = 30,
        check: bool = True,
        context: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal inspections
        calls.append(arguments)
        if arguments[:2] == ["image", "inspect"]:
            inspections += 1
            if inspections == 1:
                return subprocess.CompletedProcess(
                    arguments,
                    1,
                    stdout="",
                    stderr="Error: No such image",
                )
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout=json.dumps([_image(reference)]),
                stderr="",
            )
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(provisioning, "_docker", fake_docker)

    records = ensure_locked_images(
        _lease(),
        [{"identity": "oci-image:sha256:" + "5" * 64, "reference": reference}],
    )

    assert records[0]["cache"] == "miss"
    assert calls == [
        ["image", "inspect", reference],
        ["pull", "--platform", "linux/amd64", reference],
        ["image", "inspect", reference],
    ]


def test_digest_hit_rejects_poisoned_repository_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = "registry.example/repository@sha256:" + "4" * 64
    poisoned = _image("registry.example/repository@sha256:" + "6" * 64)
    monkeypatch.setattr(
        provisioning,
        "_docker",
        lambda arguments, timeout=30, check=True, context=None: (
            subprocess.CompletedProcess(
                arguments,
                0,
                stdout=json.dumps([poisoned]),
                stderr="",
            )
        ),
    )

    with pytest.raises(ScenarioPackageError) as rejected:
        ensure_locked_images(
            _lease(),
            [{"identity": "oci-image:sha256:" + "5" * 64, "reference": reference}],
        )

    assert rejected.value.classification == "provisioning-digest-mismatch"


def test_target_config_requires_distinct_visibility_stores(tmp_path: Path) -> None:
    config = tmp_path / "targets.yaml"
    config.write_text(
        "schema_version: 1\n"
        "visibility_domains:\n"
        "  public:\n"
        "    docker_context: shared\n"
        "    platform: linux/amd64\n"
        "  private:\n"
        "    docker_context: shared\n"
        "    platform: linux/amd64\n",
        encoding="utf-8",
    )

    with pytest.raises(ScenarioPackageError) as rejected:
        load_target_config(config, visibility="public")

    assert rejected.value.classification == "invalid-provisioning-target"


def _preflight_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    package = tmp_path / "package"
    package.mkdir()
    (package / "scenario.yaml").write_text(
        "scenario:\n  visibility: public\n", encoding="utf-8"
    )
    lock = {
        "harbor": {"commit": provisioning.HARBOR_COMMIT},
        "package": {"payload_sha256": "package-payload:sha256:" + "7" * 64},
        "resolved_inputs": {
            "images": [
                {
                    "identity": "oci-image:sha256:" + "4" * 64,
                    "reference": "registry.example/base@sha256:" + "4" * 64,
                }
            ]
        },
        "scenario_id": "example/preflight",
        "standard_v1": {"id": "standard-v1"},
    }
    lock_bytes = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
    (package / "scenario.lock.json").write_bytes(lock_bytes)
    requested = [
        {
            "cache": "hit",
            "image": _sealed_image(item["reference"]),
            "locked_identity": item["identity"],
            "reference": item["reference"],
        }
        for item in provisioning.locked_image_requests(lock)
    ]
    build_input = "artifact:sha256:" + "8" * 64
    runtime = [
        {
            "build_input_sha256": (
                provisioning._artifact_digest(
                    {
                        "harbor_commit": provisioning.HARBOR_COMMIT,
                        "source": provisioning.harbor_kernel_probe_reference(),
                    }
                )
                if role == "egress-control"
                else build_input
            ),
            "execution_reference": (
                provisioning.harbor_egress_image() + "--sealed"
                if role == "egress-control"
                else None
            ),
            "image": _sealed_image("registry.example/runtime@sha256:" + "9" * 64),
            "role": role,
        }
        for role in ("agent", "capture", "egress-control", "verifier")
    ]
    source = {
        "harbor": lock["harbor"],
        "package_lock_sha256": str(
            provisioning.TypedDigest.from_bytes(
                provisioning.DigestKind.PACKAGE_LOCK, lock_bytes
            )
        ),
        "package_payload_sha256": lock["package"]["payload_sha256"],
        "qualification_record_sha256": None,
        "standard_v1": lock["standard_v1"],
    }
    manifest: dict[str, object] = {
        "lifecycle_state": "candidate",
        "requested_images": requested,
        "runtime_images": runtime,
        "scenario_id": lock["scenario_id"],
        "source": source,
        "target": _lease().store,
        "visibility_domain": "public",
    }
    return package, manifest


def _stub_preflight_runtime(
    monkeypatch: pytest.MonkeyPatch, manifest: dict[str, object]
) -> None:
    monkeypatch.setattr(
        provisioning, "check_scenario_package", lambda package: {"lock": "valid"}
    )
    monkeypatch.setattr(
        provisioning,
        "_load_manifest",
        lambda path: (manifest, b"sealed-manifest"),
    )
    monkeypatch.setattr(provisioning, "_inspect_store", lambda target: _lease().store)
    monkeypatch.setattr(
        provisioning,
        "acquire_store_read_lease",
        lambda target, visibility: nullcontext(_lease()),
    )
    monkeypatch.setattr(provisioning, "_assert_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        provisioning,
        "build_input_digest",
        lambda package, role: "artifact:sha256:" + "8" * 64,
    )


def test_image_inspection_rejects_wrong_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = "registry.example/base@sha256:" + "4" * 64
    value = _image(reference)
    value["Architecture"] = "arm64"
    monkeypatch.setattr(
        provisioning,
        "_docker",
        lambda arguments, timeout=30, check=True, context=None: (
            subprocess.CompletedProcess(
                arguments, 0, stdout=json.dumps([value]), stderr=""
            )
        ),
    )

    with pytest.raises(ScenarioPackageError) as rejected:
        provisioning._image_record(_lease().target, reference)

    assert rejected.value.classification == "provisioning-platform-mismatch"


def test_preflight_rejects_runtime_build_input_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, manifest = _preflight_fixture(tmp_path)
    _stub_preflight_runtime(monkeypatch, manifest)
    manifest["runtime_images"][0]["build_input_sha256"] = "artifact:sha256:" + "0" * 64

    with pytest.raises(ScenarioPackageError) as rejected:
        preflight(
            package,
            manifest_path=tmp_path / "manifest.json",
            mode="qualification",
            output=tmp_path / "output",
        )

    assert rejected.value.classification == "preflight-build-input-mismatch"


def test_preflight_rejects_manifest_omitting_a_locked_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, manifest = _preflight_fixture(tmp_path)
    _stub_preflight_runtime(monkeypatch, manifest)
    manifest["requested_images"].pop()

    with pytest.raises(ScenarioPackageError) as rejected:
        preflight(
            package,
            manifest_path=tmp_path / "manifest.json",
            mode="qualification",
            output=tmp_path / "output",
        )

    assert rejected.value.classification == "preflight-image-mismatch"


def test_measured_preflight_rejects_self_asserted_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, manifest = _preflight_fixture(tmp_path)
    _stub_preflight_runtime(monkeypatch, manifest)
    manifest["lifecycle_state"] = "package_qualified"

    with pytest.raises(ScenarioPackageError) as rejected:
        preflight(
            package,
            manifest_path=tmp_path / "manifest.json",
            mode="measured",
            output=tmp_path / "output",
        )

    assert rejected.value.classification == "preflight-ineligible-source"


def test_physical_store_cannot_cross_visibility_domains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(provisioning, "_inspect_store", lambda target: _lease().store)
    with provisioning.acquire_store_lease(_lease().target, visibility="public"):
        pass

    with pytest.raises(ScenarioPackageError) as rejected:
        with provisioning.acquire_store_lease(_lease().target, visibility="private"):
            pass

    assert rejected.value.classification == "provisioning-target-mismatch"


def test_docker_guard_denies_build_and_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_id = "sha256:" + "1" * 64
    docker = tmp_path / "real-docker"
    calls = tmp_path / "docker-calls"
    docker.write_text(
        "#!/bin/sh\n"
        f'printf \'%s|%s\n\' "$*" "${{EGRESS_CONTROL_SIDECAR_IMAGE_NAME-}}" >> {calls}\n'
        f"if [ \"${{1-}} ${{2-}}\" = \"image inspect\" ]; then printf '%s\n' '{image_id}'; fi\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    monkeypatch.setattr(provisioning.shutil, "which", lambda name: str(docker))
    guard = provisioning._write_docker_guard(
        tmp_path,
        egress_reference="harbor-prebuilt:egress--sealed",
        egress_image_id=image_id,
    )

    for arguments in (("buildx", "build", "."), ("image", "pull", "example")):
        completed = subprocess.run([guard, *arguments], check=False)
        assert completed.returncode == 125

    completed = subprocess.run([guard, "run", "example", "true"], check=False)
    assert completed.returncode == 0
    assert f"run --pull=never example true|{image_id}" in calls.read_text(
        encoding="utf-8"
    )


def test_failed_provisioning_preserves_existing_manifest(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("authoritative", encoding="utf-8")

    with pytest.raises(ScenarioPackageError) as rejected:
        provision_scenario_package(
            package,
            jobs_dir=tmp_path / "jobs",
            manifest_output=manifest,
            target_config=tmp_path / "targets.yaml",
        )

    assert rejected.value.classification == "qualification-publication-failed"
    assert manifest.read_text(encoding="utf-8") == "authoritative"


def test_context_aliases_share_physical_store_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_docker(
        arguments: list[str],
        *,
        timeout: int = 30,
        check: bool = True,
        context: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ["context", "inspect"]:
            value = [{"Endpoints": {"docker": {"Host": f"alias://{arguments[2]}"}}}]
        else:
            value = {
                "Architecture": "amd64",
                "DockerRootDir": "/var/lib/docker",
                "ID": "physical-daemon",
                "OSType": "linux",
                "ServerVersion": "29.0.0",
            }
        return subprocess.CompletedProcess(
            arguments, 0, stdout=json.dumps(value), stderr=""
        )

    monkeypatch.setattr(provisioning, "_docker", fake_docker)
    first = provisioning._inspect_store(
        DockerTarget(context="alias-a", platform="linux/amd64")
    )
    second = provisioning._inspect_store(
        DockerTarget(context="alias-b", platform="linux/amd64")
    )

    assert first["store_identity"] == second["store_identity"]


def test_read_only_store_lease_does_not_create_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setattr(provisioning, "_inspect_store", lambda target: _lease().store)

    with pytest.raises(ScenarioPackageError) as rejected:
        with provisioning.acquire_store_read_lease(
            _lease().target, visibility="public"
        ):
            pass

    assert rejected.value.classification == "preflight-store-mismatch"
    assert not cache.exists()
