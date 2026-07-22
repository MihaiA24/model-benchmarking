from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import model_benchmark.runtime.hermes as hermes_runtime
import model_benchmark.runtime.hermes_mounted_launch as mounted_launch
from model_benchmark.declarations.canonical import (
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.conditions import (
    ConditionAdapterError,
    ConditionRunRequest,
    ConditionRunner,
)
from model_benchmark.runtime.credential_proxy import (
    CredentialProxy,
    CredentialProxyConfig,
)
from model_benchmark.runtime.hermes import (
    HERMES_ARTIFACT_BYTES,
    HERMES_ARTIFACT_CONTAINER_PATH,
    HERMES_ARTIFACT_IDENTITY,
    HERMES_ENVIRONMENT_NAMES,
    HERMES_IMAGE_BYTES,
    HERMES_IMAGE_ID,
    HERMES_IMAGE_IDENTITY,
    HERMES_IMAGE_REFERENCE,
    HERMES_RELEASE_COMMIT,
    HERMES_RELEASE_TAG,
    HERMES_SHIM_IDENTITY,
    HERMES_VERSION,
    HermesProvisioning,
    evaluate_hermes_qualification,
    load_hermes_condition_lock,
    provision_hermes,
    sealed_hermes_process,
)


_REAL_KEY = "provider-secret-value"
_MODEL = "locked/model"
_BRIEF = b"Implement the exact locked behavior.\n"


def test_condition_lock_seals_exact_stock_hermes_profile(
    acceptance_observation: Any,
) -> None:
    data, lock, identity = load_hermes_condition_lock()

    assert canonical_json_bytes(dict(lock)) == data
    assert lock["artifact"] == {
        "digest": HERMES_ARTIFACT_IDENTITY,
        "kind": "native-executable",
        "platform": "linux/amd64",
    }
    adapter = lock["adapter"]
    assert isinstance(adapter, dict)
    assert adapter["non_interactive"] is True
    assert adapter["self_update"] is False
    assert adapter["environment_names"] == list(HERMES_ENVIRONMENT_NAMES)
    configuration = adapter["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["artifact_bytes"] == HERMES_ARTIFACT_BYTES
    assert configuration["artifact_commit"] == HERMES_RELEASE_COMMIT
    assert configuration["artifact_container_path"] == HERMES_ARTIFACT_CONTAINER_PATH
    assert configuration["artifact_version"] == HERMES_VERSION
    assert configuration["auth_persistence"] is False
    assert configuration["rules_memory_skills_injection"] is False
    assert configuration["runtime_installation"] is False
    assert configuration["session_persistence"] is False
    assert configuration["instruction_transport"] == (
        "oneshot-argument-with-native-tools"
    )
    assert configuration["native_behavior"] == {
        "compaction": "stock",
        "planning": "stock",
        "retries": "stock",
        "tools": "stock",
    }
    assert configuration["runtime_relocation"] == mounted_launch.relocation_contract()
    assert configuration["fixed_environment"] == {
        "HERMES_DISABLE_LAZY_INSTALLS": "1",
        "HERMES_HOME": "fresh-home/.hermes",
    }
    assert configuration["hermes_config_yaml"] == {
        "model": {
            "api_mode": "chat_completions",
            "base_url": "manifest-provider-base-url",
            "default": "manifest-provider-model",
            "provider": "custom:model-benchmark-proxy",
        },
        "providers": {
            "model-benchmark-proxy": {
                "api": "manifest-provider-base-url",
                "default_model": "manifest-provider-model",
                "key_env": "MODEL_BENCHMARK_PROXY_TOKEN",
                "name": "Model Benchmark Credential Proxy",
                "transport": "chat_completions",
            }
        },
    }
    assert configuration["provision"] == {
        "image_bytes": HERMES_IMAGE_BYTES,
        "image_id": HERMES_IMAGE_ID,
        "image_identity": HERMES_IMAGE_IDENTITY,
        "image_reference": HERMES_IMAGE_REFERENCE,
        "network": "provision-only",
        "operation": "pull-exact-image-verify-commit-extract-executable",
        "release_tag": HERMES_RELEASE_TAG,
    }
    assert configuration["launch_shim"]["digest"] == HERMES_SHIM_IDENTITY
    acceptance_observation(
        "sealed-hermes-identities",
        {
            "artifact": HERMES_ARTIFACT_IDENTITY,
            "condition": str(identity),
            "image": HERMES_IMAGE_IDENTITY,
            "launch_shim": HERMES_SHIM_IDENTITY,
        },
    )


def test_provision_pulls_exact_image_once_and_warm_preflight_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acceptance_observation: Any,
) -> None:
    artifact = b"#!/bin/sh\nexit 0\n"
    artifact_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact))
    image_digest = "1" * 64
    image_identity = f"oci-image:sha256:{image_digest}"
    image_reference = f"registry.example/hermes@sha256:{image_digest}"
    image_id = "sha256:" + "2" * 64
    image_bytes = 123_456
    _, original, _ = load_hermes_condition_lock()
    lock = json.loads(json.dumps(dict(original)))
    lock["artifact"]["digest"] = artifact_identity
    configuration = lock["adapter"]["configuration"]
    configuration["artifact_bytes"] = len(artifact)
    provision = configuration["provision"]
    provision["image_bytes"] = image_bytes
    provision["image_id"] = image_id
    provision["image_identity"] = image_identity
    provision["image_reference"] = image_reference
    lock_bytes = canonical_json_bytes(lock)
    lock_path = tmp_path / "hermes.condition.json"
    lock_path.write_bytes(lock_bytes)

    monkeypatch.setattr(hermes_runtime, "HERMES_ARTIFACT_BYTES", len(artifact))
    monkeypatch.setattr(hermes_runtime, "HERMES_ARTIFACT_IDENTITY", artifact_identity)
    monkeypatch.setattr(hermes_runtime, "HERMES_IMAGE_BYTES", image_bytes)
    monkeypatch.setattr(hermes_runtime, "HERMES_IMAGE_ID", image_id)
    monkeypatch.setattr(hermes_runtime, "HERMES_IMAGE_IDENTITY", image_identity)
    monkeypatch.setattr(hermes_runtime, "HERMES_IMAGE_REFERENCE", image_reference)
    monkeypatch.setattr(hermes_runtime, "hermes_condition_lock_path", lambda: lock_path)
    image_record = {
        "architecture": "amd64",
        "bytes": image_bytes,
        "id": image_id,
        "identity": image_identity,
        "os": "linux",
        "reference": image_reference,
        "release_commit": HERMES_RELEASE_COMMIT,
        "release_tag": HERMES_RELEASE_TAG,
    }
    pulled = False
    pulls: list[list[str]] = []
    extractions: list[Path] = []
    container_runtime = tmp_path / "docker"
    container_runtime.write_bytes(b"#!/bin/sh\nexit 0\n")
    container_runtime.chmod(0o555)

    def inspect_image() -> dict[str, object] | None:
        return image_record if pulled else None

    def docker(
        arguments: list[str],
        *,
        timeout: int = 30,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal pulled
        assert arguments == ["pull", "--platform", "linux/amd64", image_reference]
        assert timeout == 600
        assert check is True
        pulls.append(arguments)
        pulled = True
        return subprocess.CompletedProcess(arguments, 0, "", "")

    def extract(destination: Path) -> None:
        extractions.append(destination)
        destination.write_bytes(artifact)
        destination.chmod(0o555)

    monkeypatch.setattr(hermes_runtime, "_inspect_image", inspect_image)
    monkeypatch.setattr(hermes_runtime, "_docker", docker)
    monkeypatch.setattr(
        hermes_runtime,
        "_container_runtime_path",
        lambda: container_runtime,
    )
    monkeypatch.setattr(hermes_runtime, "_extract_artifact", extract)
    cache = tmp_path / "cache"
    cold = provision_hermes(cache, lock_bytes)
    paths = (cold.artifact_path, cold.launch_shim_path, cold.manifest_path)
    before = {path: (path.stat().st_mtime_ns, path.stat().st_mode) for path in paths}
    warm = provision_hermes(cache, lock_bytes)
    after = {path: (path.stat().st_mtime_ns, path.stat().st_mode) for path in paths}

    assert len(pulls) == 1
    assert len(extractions) == 1
    assert cold == warm
    assert before == after
    assert stat.S_IMODE(cold.artifact_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(cold.launch_shim_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(cold.manifest_path.stat().st_mode) == 0o400
    manifest = load_canonical_json(cold.manifest_path.read_bytes())
    assert manifest["network"] == "provision-only"
    assert manifest["image"] == image_record
    acceptance_observation(
        "hermes-digest-first-warm-preflight",
        {
            "extraction_count": len(extractions),
            "pull_count": len(pulls),
            "read_only": before == after,
        },
    )

    cold.artifact_path.chmod(0o755)
    cold.artifact_path.write_bytes(b"changed")
    with pytest.raises(ConditionAdapterError, match="cached executable") as captured:
        hermes_runtime.preflight_hermes(cache, lock_bytes)
    assert captured.value.reason_code == "condition-unqualified"


def _fake_hermes(tmp_path: Path) -> tuple[Path, Path]:
    artifact = tmp_path / "hermes"
    artifact.write_bytes(b"#!/bin/sh\nexit 0\n")
    artifact.chmod(0o555)
    docker = tmp_path / "docker"
    docker.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import http.client
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

arguments = sys.argv[1:]
if not arguments or arguments[0] != "run":
    raise SystemExit(90)

def option(name):
    return arguments[arguments.index(name) + 1]

volumes = [
    arguments[index + 1]
    for index, value in enumerate(arguments)
    if value == "--volume"
]
home = Path(next(value.split(":", 1)[0] for value in volumes if value.endswith(":/opt/data")))
workspace = Path(
    next(value.split(":", 1)[0] for value in volumes if value.endswith(":/workspace"))
)
if Path.cwd() != workspace:
    raise SystemExit(91)
if option("--network") != "host" or option("--platform") != "linux/amd64":
    raise SystemExit(92)
if option("--entrypoint") != "/opt/hermes/bin/hermes":
    raise SystemExit(93)
if option("--user") != f"{os.getuid()}:{os.getgid()}":
    raise SystemExit(94)
environment = [
    arguments[index + 1]
    for index, value in enumerate(arguments)
    if value == "--env"
]
if "HERMES_DISABLE_LAZY_INSTALLS=1" not in environment:
    raise SystemExit(95)
image_index = arguments.index(
    "nousresearch/hermes-agent@sha256:"
    "3db34ce19adfa080736a2a3feb0316dbcccc588faa9afe7fd8ae1c03b4f1a53a"
)
hermes_arguments = arguments[image_index + 1:]
if len(hermes_arguments) != 9 or hermes_arguments[:2] != ["--ignore-rules", "-z"]:
    raise SystemExit(96)
brief = hermes_arguments[2]
if hermes_arguments[3:7] != [
    "--provider",
    "custom:model-benchmark-proxy",
    "--model",
    "locked/model",
]:
    raise SystemExit(97)
if hermes_arguments[7] != "--usage-file":
    raise SystemExit(98)
usage_path = home / ".model-benchmark" / Path(hermes_arguments[8]).name
hermes_home = home / ".hermes"
marker = home / ".hermes-fresh-home"
if marker.exists():
    raise SystemExit(99)
marker.write_text("one trial", encoding="utf-8")
config = json.loads((hermes_home / "config.yaml").read_text(encoding="utf-8"))
provider = config["providers"]["model-benchmark-proxy"]
(hermes_home / "logs").mkdir(parents=True)
(hermes_home / "state.db").write_bytes(b"stock Hermes session trace")
(hermes_home / "logs/agent.log").write_text(
    "stock planning retries compaction and tools enabled\\n", encoding="utf-8"
)
unsupported = (workspace / "unsupported").exists()
usage_path.write_text(json.dumps({
    "api_calls": 0 if unsupported else 1,
    "completed": not unsupported,
    "failed": unsupported,
    "input_tokens": 0 if unsupported else 12,
    "model": "locked/model",
    "output_tokens": 0 if unsupported else 5,
    "provider": "custom",
    "total_tokens": 0 if unsupported else 17,
}, sort_keys=True), encoding="utf-8")
if unsupported:
    raise SystemExit(100)
parsed = urlsplit(provider["api"])
capability_body = json.dumps(
    {"name": "locked/model"},
    separators=(",", ":"),
).encode()
capability = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
capability.request(
    "POST",
    parsed.path + "/api/show",
    body=capability_body,
    headers={
        "Authorization": "Bearer " + os.environ[provider["key_env"]],
        "Content-Type": "application/json",
    },
)
capability_response = capability.getresponse()
capability_value = json.loads(capability_response.read())
if (
    capability_response.status != 200
    or capability_value.get("model_info", {}).get("context_length") != 131072
):
    raise SystemExit(101)
capability.close()
body = json.dumps({
    "messages": [{"content": brief, "role": "user"}],
    "model": "locked/model",
    "stream": True,
    "stream_options": {"include_usage": True},
    "tools": [{"function": {"name": "terminal"}, "type": "function"}],
}, separators=(",", ":")).encode()
connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
connection.request(
    "POST",
    parsed.path + "/chat/completions",
    body=body,
    headers={
        "Authorization": "Bearer " + os.environ[provider["key_env"]],
        "Content-Type": "application/json",
    },
)
response = connection.getresponse()
response.read()
if response.status != 200:
    raise SystemExit(101)
connection.close()
(workspace / "hermes-observation.json").write_text(json.dumps({
    "brief": brief,
    "config": config,
    "workspace": str(workspace),
}, sort_keys=True), encoding="utf-8")
print("done", flush=True)
""",
        encoding="utf-8",
    )
    docker.chmod(0o555)
    return artifact, docker


def _install_fake_condition(
    monkeypatch: pytest.MonkeyPatch,
    artifact: Path,
) -> None:
    artifact_data = artifact.read_bytes()
    artifact_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact_data))
    condition_identity = TypedDigest.from_bytes(
        DigestKind.FUNCTIONAL_V1_CONDITION,
        canonical_json_bytes({"artifact": artifact_identity}),
    )
    lock = {
        "adapter": {
            "configuration": {
                "artifact_bytes": len(artifact_data),
                "launch_shim": {"digest": HERMES_SHIM_IDENTITY},
                "provision": {
                    "image_id": HERMES_IMAGE_ID,
                    "image_identity": HERMES_IMAGE_IDENTITY,
                    "image_reference": HERMES_IMAGE_REFERENCE,
                },
            }
        },
        "artifact": {"digest": artifact_identity},
    }
    monkeypatch.setattr(
        hermes_runtime,
        "load_hermes_condition_lock",
        lambda: (b"", lock, condition_identity),
    )


_CAPABILITY_REPLY = {
    "cost_usd": "0.00",
    "model": _MODEL,
    "model_info": {"context_length": 131_072},
    "usage": {"total_tokens": 0},
}


def _run_trial(
    recording_provider: Any,
    tmp_path: Path,
    *,
    name: str,
    artifact: Path,
    container_runtime: Path,
    unsupported: bool = False,
) -> tuple[Any, Any, Path, Path]:
    repository = tmp_path / f"source-{name}"
    repository.mkdir()
    (repository / "baseline.txt").write_text("sealed baseline\n", encoding="utf-8")
    if unsupported:
        (repository / "unsupported").write_text("true\n", encoding="utf-8")
    else:
        recording_provider.enqueue_json(_CAPABILITY_REPLY)
    token = f"opaque-token-{name}"
    evidence_path = tmp_path / f"proxy-{name}.jsonl"
    proxy = CredentialProxy(
        CredentialProxyConfig(
            upstream_base_url=recording_provider.base_url,
            model=_MODEL,
            real_api_key=_REAL_KEY,
            trial_token=token,
            provider_tokens_per_trial=100_000,
            stop_after_cost_usd_per_trial=Decimal("5.00"),
            evidence_path=evidence_path,
            allowed_endpoint_paths=("/api/show", "/chat/completions"),
        )
    )
    artifact_identity = str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact.read_bytes())
    )
    provisioning = HermesProvisioning(
        condition_identity=str(hermes_runtime.load_hermes_condition_lock()[2]),
        image_reference=HERMES_IMAGE_REFERENCE,
        image_identity=HERMES_IMAGE_IDENTITY,
        image_id=HERMES_IMAGE_ID,
        container_runtime_path=container_runtime,
        artifact_path=artifact,
        artifact_identity=artifact_identity,
        launch_shim_path=hermes_runtime.hermes_launch_shim_path(),
        launch_shim_identity=HERMES_SHIM_IDENTITY,
        manifest_path=tmp_path / "unused-provisioning.json",
    )
    trial_root = tmp_path / f"trial-{name}"
    with proxy:
        result = ConditionRunner().run(
            ConditionRunRequest(
                process=sealed_hermes_process(
                    provisioning,
                    proxy_base_url=proxy.base_url,
                    provider_model=_MODEL,
                    trial_proxy_token=token,
                ),
                repository_source=repository,
                trial_root=trial_root,
                developer_brief=_BRIEF,
                trial_proxy_token=token,
                sensitive_values=(_REAL_KEY, token),
            )
        )
    return result, proxy.snapshot, evidence_path, trial_root


def test_fresh_oneshot_trials_preserve_native_behavior_and_complete_evidence(
    recording_provider: Any,
    tmp_path: Path,
    acceptance_observation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, container_runtime = _fake_hermes(tmp_path)
    _install_fake_condition(monkeypatch, artifact)
    first = _run_trial(
        recording_provider,
        tmp_path,
        name="one",
        artifact=artifact,
        container_runtime=container_runtime,
    )
    second = _run_trial(
        recording_provider,
        tmp_path,
        name="two",
        artifact=artifact,
        container_runtime=container_runtime,
    )

    assert len(recording_provider.requests) == 4, [
        (item[0].exit_code, item[0].capture_root.joinpath("stderr.bin").read_bytes())
        for item in (first, second)
    ]
    for index, (result, snapshot, evidence_path, trial_root) in enumerate(
        (first, second)
    ):
        capability = recording_provider.requests[index * 2]
        request = recording_provider.requests[index * 2 + 1]
        capability_body = json.loads(capability.body)
        body = json.loads(request.body)
        observation = json.loads(
            (trial_root / "repository/hermes-observation.json").read_text(
                encoding="utf-8"
            )
        )
        observed_brief = body["messages"][0]["content"].encode()
        qualification = evaluate_hermes_qualification(
            result,
            evidence_path,
            expected_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
            observed_brief_sha256="sha256:"
            + hashlib.sha256(observed_brief).hexdigest(),
            workspace_verified=(
                observation["workspace"] == str(trial_root / "repository")
            ),
            unexpected_network_requests=0,
        )
        delivery = json.loads(
            (
                result.capture_root
                / "native/home/.model-benchmark/hermes-delivery.json"
            ).read_text(encoding="utf-8")
        )
        usage = json.loads(
            (
                result.capture_root / "native/home/.model-benchmark/hermes-usage.json"
            ).read_text(encoding="utf-8")
        )

        assert qualification.qualified is True
        assert qualification.reason_code == "qualified"
        assert qualification.evidence["provider_response_count"] == 2
        assert result.exit_code == 0
        assert result.signal is None
        assert result.process_tree_terminated is True
        assert result.infrastructure_valid is True
        assert result.environment_names == HERMES_ENVIRONMENT_NAMES
        assert result.capture_root.joinpath("stdout.bin").read_bytes() == b"done\n"
        assert result.capture_root.joinpath("stderr.bin").read_bytes() == b""
        for path in (
            "home/.hermes/logs/agent.log",
            "home/.hermes/state.db",
            "home/.model-benchmark/hermes-delivery.json",
            "home/.model-benchmark/hermes-usage.json",
        ):
            assert path in result.artifact_digests
        assert delivery["auth_persistence"] is False
        assert delivery["image_identity"] == HERMES_IMAGE_IDENTITY
        assert delivery["brief_sha256"] == (
            "sha256:" + hashlib.sha256(_BRIEF).hexdigest()
        )
        assert delivery["memory_injection"] is False
        assert delivery["model"] == _MODEL
        assert delivery["provider"] == "model-benchmark-proxy"
        assert delivery["proxy_base_url"].startswith("http://127.0.0.1:")
        assert delivery["rules_injection"] is False
        assert delivery["runtime_installation"] is False
        assert delivery["skills_injection"] is False
        assert delivery["transport"] == "oneshot-argument-with-native-tools"
        assert delivery["workspace"] == str(trial_root / "repository")
        assert usage["api_calls"] == 1
        assert usage["completed"] is True
        assert usage["failed"] is False
        assert usage["total_tokens"] == 17
        assert snapshot.request_count == 2
        assert snapshot.provider_tokens == 17
        assert snapshot.provider_cost_usd == "0.10"
        assert capability.path == "/api/show"
        assert capability.headers["authorization"] == f"Bearer {_REAL_KEY}"
        assert capability_body == {"name": _MODEL}
        assert request.path == "/chat/completions"
        assert request.headers["authorization"] == f"Bearer {_REAL_KEY}"
        assert body["model"] == _MODEL
        assert observed_brief == _BRIEF
        assert [tool["function"]["name"] for tool in body["tools"]] == ["terminal"]
        config = observation["config"]
        assert set(config) == {"model", "providers"}
        assert "temperature" not in json.dumps(config)
        provider = config["providers"]["model-benchmark-proxy"]
        assert provider["api"] == delivery["proxy_base_url"]
        assert provider["default_model"] == _MODEL
        assert provider["key_env"] == "MODEL_BENCHMARK_PROXY_TOKEN"
        assert provider["transport"] == "chat_completions"
        assert not (trial_root / "home/.hermes/.env").exists()
        assert not (trial_root / "home/.hermes/auth.json").exists()
        assert (trial_root / "home/.hermes-fresh-home").is_file()
        for captured_path in result.capture_root.rglob("*"):
            if captured_path.is_file():
                captured = captured_path.read_bytes()
                assert _REAL_KEY.encode() not in captured
                token = "opaque-token-one" if index == 0 else "opaque-token-two"
                assert token.encode() not in captured

    acceptance_observation(
        "hermes-oneshot-qualified",
        {
            "fresh_homes": 2,
            "provider_requests": len(recording_provider.requests),
            "route": "/chat/completions",
        },
    )


def test_unsupported_oneshot_behavior_is_unqualified_without_fallback(
    recording_provider: Any,
    tmp_path: Path,
    acceptance_observation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, container_runtime = _fake_hermes(tmp_path)
    _install_fake_condition(monkeypatch, artifact)
    result, _, evidence_path, _ = _run_trial(
        recording_provider,
        tmp_path,
        name="unsupported",
        artifact=artifact,
        container_runtime=container_runtime,
        unsupported=True,
    )
    qualification = evaluate_hermes_qualification(
        result,
        evidence_path,
        expected_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
        observed_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
        workspace_verified=True,
        unexpected_network_requests=0,
    )

    assert qualification.qualified is False
    assert qualification.reason_code == "hermes-oneshot-unsupported"
    assert result.exit_code == 78
    assert result.process_tree_terminated is True
    assert recording_provider.requests == []
    acceptance_observation(
        "unsupported-hermes-unqualified",
        {"fallback_attempts": 0, "reason_code": qualification.reason_code},
    )


def test_image_identity_does_not_depend_on_storage_driver_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspected = {
        "Architecture": "amd64",
        "Config": {
            "Env": ["HERMES_DISABLE_LAZY_INSTALLS=1"],
            "Labels": {
                "org.opencontainers.image.revision": HERMES_RELEASE_COMMIT
            },
        },
        "Id": HERMES_IMAGE_ID,
        "Os": "linux",
        "RepoDigests": [HERMES_IMAGE_REFERENCE],
        "Size": HERMES_IMAGE_BYTES - 1,
    }
    completed = subprocess.CompletedProcess(
        ["docker"], 0, stdout=json.dumps(inspected), stderr=""
    )
    monkeypatch.setattr(hermes_runtime, "_docker", lambda *_args, **_kwargs: completed)

    record = hermes_runtime._inspect_image()

    assert record is not None
    assert record["identity"] == HERMES_IMAGE_IDENTITY
    assert record["bytes"] == HERMES_IMAGE_BYTES


_MOUNT_PREFIX = "/opt/model-benchmark-condition"


def _mounted_launch_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, Path, dict[str, Any]]:
    mount = tmp_path / _MOUNT_PREFIX.lstrip("/")
    shim = mount / "opt/hermes/bin/hermes"
    shim.parent.mkdir(parents=True)
    shim.write_bytes(b"#!/bin/sh\nexec hermes-shim\n")
    python_source = mount / mounted_launch._STOCK_PYTHON_PATH.lstrip("/")
    python_source.parent.mkdir(parents=True)
    stock_interpreter = mounted_launch._STOCK_ELF_INTERPRETER.encode() + b"\0"
    python_bytes = b"\x7fELF-test-prefix" + stock_interpreter + b"test-suffix"
    python_source.write_bytes(python_bytes)
    loader_source = mount / mounted_launch._STOCK_LOADER_PATH.lstrip("/")
    loader_source.parent.mkdir(parents=True)
    loader_bytes = b"\x7fELF-test-loader"
    loader_source.write_bytes(loader_bytes)
    suffix = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:8]
    relocated_python = Path(f"/tmp/mbp-{suffix}")
    relocated_loader = Path(f"/tmp/mbl-{suffix}")
    monkeypatch.setattr(mounted_launch, "_STOCK_PYTHON_BYTES", len(python_bytes))
    monkeypatch.setattr(
        mounted_launch, "_STOCK_PYTHON_IDENTITY", mounted_launch._identity(python_bytes)
    )
    monkeypatch.setattr(mounted_launch, "_STOCK_LOADER_BYTES", len(loader_bytes))
    monkeypatch.setattr(
        mounted_launch, "_STOCK_LOADER_IDENTITY", mounted_launch._identity(loader_bytes)
    )
    monkeypatch.setattr(mounted_launch, "_RELOCATED_PYTHON_PATH", str(relocated_python))
    monkeypatch.setattr(mounted_launch, "_RELOCATED_LOADER_PATH", str(relocated_loader))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "MODEL_BENCHMARK_PROXY_BASE_URL", "http://credential-proxy:8080/v1"
    )
    monkeypatch.setenv("MODEL_BENCHMARK_PROVIDER_MODEL", "locked/model")

    real_path = Path

    def rebased(*arguments: object) -> Path:
        candidate = real_path(*arguments)
        if candidate.is_absolute() and str(candidate).startswith(_MOUNT_PREFIX):
            return tmp_path / candidate.relative_to("/")
        return candidate

    rebased.cwd = real_path.cwd
    monkeypatch.setattr(mounted_launch, "Path", rebased)
    monkeypatch.setattr(
        mounted_launch,
        "sys",
        SimpleNamespace(
            stdin=SimpleNamespace(buffer=io.BytesIO(b"do the task")),
            stdout=SimpleNamespace(buffer=io.BytesIO()),
            stderr=SimpleNamespace(buffer=io.BytesIO()),
        ),
    )
    captured: dict[str, Any] = {
        "loader_bytes": loader_bytes,
        "python_bytes": python_bytes,
        "python_source": python_source,
        "relocated_loader": relocated_loader,
        "relocated_python": relocated_python,
    }
    return mounted_launch._digest(shim), home, captured


def _fake_hermes_run(
    captured: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    usage: dict[str, Any],
) -> None:
    def run(
        arguments: list[str], *, cwd: Path, env: dict[str, str], **_: Any
    ) -> subprocess.CompletedProcess[bytes]:
        captured["arguments"] = arguments
        captured["env"] = env
        python_path = Path(arguments[0])
        loader_path = Path(mounted_launch._RELOCATED_LOADER_PATH)
        captured["published_python"] = python_path.read_bytes()
        captured["published_loader"] = loader_path.read_bytes()
        captured["published_python_mode"] = stat.S_IMODE(python_path.stat().st_mode)
        captured["published_loader_mode"] = stat.S_IMODE(loader_path.stat().st_mode)
        usage_path = Path(arguments[arguments.index("--usage-file") + 1])
        usage_path.write_text(json.dumps(usage), encoding="utf-8")
        return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(
        mounted_launch,
        "subprocess",
        SimpleNamespace(
            run=run,
            PIPE=subprocess.PIPE,
            SubprocessError=subprocess.SubprocessError,
        ),
    )


_VALID_USAGE = {
    "api_calls": 3,
    "completed": True,
    "failed": False,
    "input_tokens": 10,
    "model": "locked/model",
    "output_tokens": 5,
    "total_tokens": 15,
}


def test_mounted_launch_pins_the_hermes_environment_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, home, captured = _mounted_launch_fixture(tmp_path, monkeypatch)
    _fake_hermes_run(captured, monkeypatch, _VALID_USAGE)

    assert mounted_launch.main(["--artifact-identity", identity]) == 0

    mount = tmp_path / _MOUNT_PREFIX.lstrip("/")
    hermes_root = mount / "opt/hermes"
    environment = captured["env"]
    assert environment["PYTHONPATH"] == ":".join(
        (
            str(hermes_root),
            str(hermes_root / ".venv/lib/python3.13/site-packages"),
            str(mount / "opt/model-benchmark-runtime"),
        )
    )
    assert environment["PYTHONHOME"] == str(mount / "usr")
    assert environment["HERMES_DISABLE_LAZY_INSTALLS"] == "1"
    assert environment["HERMES_INFERENCE_MODEL"] == "locked/model"
    assert environment["HERMES_INFERENCE_PROVIDER"] == (
        "custom:model-benchmark-proxy"
    )
    assert "MODEL_BENCHMARK_HERMES_CHILD_PYTHON" not in environment
    assert "MODEL_BENCHMARK_HERMES_TOOL_PATH" not in environment
    before = mounted_launch._STOCK_ELF_INTERPRETER.encode() + b"\0"
    after = mounted_launch._RELOCATED_LOADER_PATH.encode() + b"\0"
    assert captured["published_python"] == captured["python_bytes"].replace(
        before, after.ljust(len(before), b"\0")
    )
    assert captured["published_loader"] == captured["loader_bytes"]
    assert captured["published_python_mode"] == 0o500
    assert captured["published_loader_mode"] == 0o500
    assert not captured["relocated_python"].exists()
    assert not captured["relocated_loader"].exists()
    arguments = captured["arguments"]
    assert arguments[:2] == [
        str(captured["relocated_python"]),
        str(hermes_root / ".venv/bin/hermes"),
    ]
    assert "--bootstrap" not in arguments
    assert arguments[arguments.index("-z") + 1] == "do the task"
    assert arguments[arguments.index("--model") + 1] == "locked/model"
    config = json.loads(
        (home / ".hermes/config.yaml").read_text(encoding="utf-8")
    )
    assert config["providers"]["model-benchmark-proxy"]["key_env"] == (
        "MODEL_BENCHMARK_PROXY_TOKEN"
    )
    assert config["providers"]["model-benchmark-proxy"]["api"] == (
        "http://credential-proxy:8080/v1"
    )
    delivery = json.loads(
        (home / ".model-benchmark/hermes-delivery.json").read_text(encoding="utf-8")
    )
    assert delivery["transport"] == "oneshot-argument-with-native-tools"
    assert delivery["runtime_installation"] is False
    assert delivery["runtime_relocation"] == mounted_launch.relocation_contract()


def test_mounted_launch_rejects_an_undeclared_mounted_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, _, captured = _mounted_launch_fixture(tmp_path, monkeypatch)
    captured["python_source"].write_bytes(captured["python_bytes"] + b"changed")
    _fake_hermes_run(captured, monkeypatch, _VALID_USAGE)

    assert mounted_launch.main(["--artifact-identity", identity]) == 78
    assert "arguments" not in captured
    assert not captured["relocated_python"].exists()
    assert not captured["relocated_loader"].exists()


def test_mounted_launch_rejects_an_invalid_usage_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, _, captured = _mounted_launch_fixture(tmp_path, monkeypatch)
    _fake_hermes_run(captured, monkeypatch, {**_VALID_USAGE, "failed": True})

    assert mounted_launch.main(["--artifact-identity", identity]) == 78


def test_mounted_launch_fails_closed_without_the_mounted_tree() -> None:
    # On any host without the sealed condition mount the launch must exit
    # unqualified, never crash.
    assert (
        mounted_launch.main(
            ["--artifact-identity", "artifact:sha256:" + "0" * 64]
        )
        == 78
    )


@pytest.mark.parametrize(
    ("mutation", "valid"),
    [
        ({}, True),
        ({"completed": False}, False),
        ({"failed": True}, False),
        ({"model": "other/model"}, False),
        ({"api_calls": True}, False),
        ({"total_tokens": "15"}, False),
    ],
)
def test_mounted_launch_usage_matrix(
    tmp_path: Path,
    mutation: dict[str, Any],
    valid: bool,
) -> None:
    usage_path = tmp_path / "usage.json"
    usage_path.write_text(json.dumps({**_VALID_USAGE, **mutation}), encoding="utf-8")

    assert mounted_launch._valid_usage(usage_path, "locked/model") is valid
