from __future__ import annotations

import gzip
import hashlib
import io
import json
import stat
import sys
import tarfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import model_benchmark.runtime.opencode as opencode_runtime
import model_benchmark.runtime.opencode_launch as opencode_launch
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
from model_benchmark.runtime.opencode import (
    OPENCODE_ARCHIVE_BYTES,
    OPENCODE_ARCHIVE_IDENTITY,
    OPENCODE_ARCHIVE_URL,
    OPENCODE_ARTIFACT_BYTES,
    OPENCODE_ARTIFACT_IDENTITY,
    OPENCODE_ENVIRONMENT_NAMES,
    OPENCODE_RELEASE_COMMIT,
    OPENCODE_SHIM_IDENTITY,
    OPENCODE_VERSION,
    OpenCodeProvisioning,
    evaluate_opencode_qualification,
    load_opencode_condition_lock,
    provision_opencode,
    sealed_opencode_process,
)


_REAL_KEY = "provider-secret-value"
_MODEL = "locked/model"
_BRIEF = b"Implement the exact locked behavior. Run `python task.py --output generated.csv`.\n"


def test_condition_lock_seals_exact_stock_opencode_profile(
    acceptance_observation: Any,
) -> None:
    data, lock, identity = load_opencode_condition_lock()

    assert canonical_json_bytes(dict(lock)) == data
    assert lock["artifact"] == {
        "digest": OPENCODE_ARTIFACT_IDENTITY,
        "kind": "native-executable",
        "platform": "linux/amd64",
    }
    adapter = lock["adapter"]
    assert isinstance(adapter, dict)
    assert adapter["non_interactive"] is True
    assert adapter["self_update"] is False
    assert adapter["environment_names"] == list(OPENCODE_ENVIRONMENT_NAMES)
    configuration = adapter["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["archive_bytes"] == OPENCODE_ARCHIVE_BYTES
    assert configuration["archive_digest"] == OPENCODE_ARCHIVE_IDENTITY
    assert configuration["archive_source"] == OPENCODE_ARCHIVE_URL
    assert configuration["artifact_bytes"] == OPENCODE_ARTIFACT_BYTES
    assert configuration["artifact_commit"] == OPENCODE_RELEASE_COMMIT
    assert configuration["artifact_version"] == OPENCODE_VERSION
    assert configuration["auth_persistence"] is False
    assert configuration["runtime_installation"] is False
    assert configuration["session_persistence"] is False
    assert configuration["instruction_transport"] == "run-stdin-json-events"
    assert configuration["launch_shim"]["digest"] == OPENCODE_SHIM_IDENTITY
    assert configuration["fixed_environment"] == {
        "OPENCODE_CONFIG": "fresh-home/.model-benchmark/opencode.json",
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
    }
    assert "workspace_cleanup" not in configuration
    assert configuration["opencode_json"] == {
        "autoupdate": False,
        "mcp": {},
        "plugin": [],
        "provider": {
            "model-benchmark-proxy": {
                "models": {
                    "manifest-provider-model": {
                        "name": "manifest-provider-model",
                    }
                },
                "name": "Model Benchmark Credential Proxy",
                "npm": "manifest-provider-npm",
                "options": {
                    "apiKey": "{env:MODEL_BENCHMARK_PROXY_TOKEN}",
                    "baseURL": "manifest-provider-base-url",
                },
            }
        },
        "share": "disabled",
    }
    assert configuration["provision"] == {
        "archive_format": "tar-gzip",
        "archive_member": "opencode",
        "network": "provision-only",
        "operation": "download-once-verify-sha256-extract-single-file",
    }
    acceptance_observation(
        "sealed-opencode-identities",
        {
            "archive": OPENCODE_ARCHIVE_IDENTITY,
            "artifact": OPENCODE_ARTIFACT_IDENTITY,
            "condition": str(identity),
            "launch_shim": OPENCODE_SHIM_IDENTITY,
        },
    )


def _archive_bytes(artifact: bytes) -> bytes:
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as gzip_file:
        with tarfile.open(fileobj=gzip_file, mode="w") as archive:
            member = tarfile.TarInfo("opencode")
            member.mode = 0o755
            member.size = len(artifact)
            member.mtime = 0
            archive.addfile(member, io.BytesIO(artifact))
    return compressed.getvalue()


def test_provision_extracts_once_and_warm_preflight_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acceptance_observation: Any,
) -> None:
    artifact = b"#!/bin/sh\nexit 0\n"
    archive = _archive_bytes(artifact)
    artifact_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact))
    archive_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, archive))
    artifact_url = "https://artifacts.example/opencode-v1.17.18-linux-x64.tar.gz"
    _, original, _ = load_opencode_condition_lock()
    lock = json.loads(json.dumps(dict(original)))
    lock["artifact"]["digest"] = artifact_identity
    configuration = lock["adapter"]["configuration"]
    configuration["archive_bytes"] = len(archive)
    configuration["archive_digest"] = archive_identity
    configuration["archive_source"] = artifact_url
    configuration["artifact_bytes"] = len(artifact)
    lock_bytes = canonical_json_bytes(lock)
    lock_path = tmp_path / "opencode.condition.json"
    lock_path.write_bytes(lock_bytes)

    monkeypatch.setattr(opencode_runtime, "OPENCODE_ARCHIVE_BYTES", len(archive))
    monkeypatch.setattr(opencode_runtime, "OPENCODE_ARCHIVE_IDENTITY", archive_identity)
    monkeypatch.setattr(opencode_runtime, "OPENCODE_ARCHIVE_URL", artifact_url)
    monkeypatch.setattr(opencode_runtime, "OPENCODE_ARTIFACT_BYTES", len(artifact))
    monkeypatch.setattr(
        opencode_runtime, "OPENCODE_ARTIFACT_IDENTITY", artifact_identity
    )
    monkeypatch.setattr(
        opencode_runtime, "opencode_condition_lock_path", lambda: lock_path
    )
    calls: list[str] = []

    def open_artifact(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout == 120
        calls.append(url)
        return io.BytesIO(archive)

    monkeypatch.setattr(opencode_runtime.urllib.request, "urlopen", open_artifact)
    cache = tmp_path / "cache"
    cold = provision_opencode(cache, lock_bytes)
    paths = (
        cold.archive_path,
        cold.artifact_path,
        cold.launch_shim_path,
        cold.manifest_path,
    )
    before = {path: (path.stat().st_mtime_ns, path.stat().st_mode) for path in paths}
    warm = provision_opencode(cache, lock_bytes)
    after = {path: (path.stat().st_mtime_ns, path.stat().st_mode) for path in paths}

    assert calls == [artifact_url]
    assert cold == warm
    assert before == after
    assert cold.artifact_path.read_bytes() == artifact
    assert stat.S_IMODE(cold.archive_path.stat().st_mode) == 0o444
    assert stat.S_IMODE(cold.artifact_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(cold.launch_shim_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(cold.manifest_path.stat().st_mode) == 0o400
    manifest = load_canonical_json(cold.manifest_path.read_bytes())
    assert manifest["network"] == "provision-only"
    assert manifest["extraction"] == {
        "archive_format": "tar-gzip",
        "archive_member": "opencode",
    }
    acceptance_observation(
        "opencode-digest-first-warm-preflight",
        {"download_count": len(calls), "read_only": before == after},
    )

    cold.artifact_path.chmod(0o755)
    cold.artifact_path.write_bytes(b"changed")
    with pytest.raises(ConditionAdapterError, match="cached executable") as captured:
        opencode_runtime.preflight_opencode(cache, lock_bytes)
    assert captured.value.reason_code == "condition-unqualified"


def _fake_opencode(tmp_path: Path) -> Path:
    path = tmp_path / "opencode"
    path.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import http.client
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

home = Path(os.environ["HOME"])
marker = home / ".opencode-fresh-home"
if marker.exists():
    raise SystemExit(91)
marker.write_text("one trial", encoding="utf-8")
arguments = sys.argv[1:]
if arguments != ["run", "--format", "json", "--model", "model-benchmark-proxy/locked/model"]:
    raise SystemExit(92)
if os.environ.get("OPENCODE_DISABLE_AUTOUPDATE") != "true":
    raise SystemExit(93)
if os.environ.get("OPENCODE_DISABLE_PROJECT_CONFIG") != "true":
    raise SystemExit(94)
config_path = Path(os.environ["OPENCODE_CONFIG"])
if config_path != home / ".model-benchmark/opencode.json":
    raise SystemExit(95)
config = json.loads(config_path.read_text(encoding="utf-8"))
provider = config["provider"]["model-benchmark-proxy"]
brief = sys.stdin.buffer.read()
(Path.cwd() / "generated.csv").write_text("derived output", encoding="utf-8")
if (Path.cwd() / "unsupported").exists():
    raise SystemExit(96)
parsed = urlsplit(provider["options"]["baseURL"])
for purpose in ("title", "task"):
    messages = [
        {"content": "stock OpenCode " + purpose + " prompt", "role": "system"},
        {"content": brief.decode("utf-8"), "role": "user"},
    ]
    body = json.dumps(
        {
            "messages": messages,
            "model": next(iter(provider["models"])),
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        separators=(",", ":"),
    ).encode()
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    connection.request(
        "POST",
        parsed.path + "/chat/completions",
        body=body,
        headers={
            "Authorization": "Bearer " + os.environ["MODEL_BENCHMARK_PROXY_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    response.read()
    if response.status != 200:
        raise SystemExit(97)
    connection.close()
(Path.cwd() / "opencode-observation.json").write_text(
    json.dumps(
        {
            "brief": brief.decode("utf-8"),
            "config": config,
            "request_count": 2,
            "workspace": str(Path.cwd()),
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
session = "ses_functional_v1"
for event in (
    {"part": {"type": "step-start"}, "sessionID": session, "type": "step_start"},
    {"part": {"text": "done", "type": "text"}, "sessionID": session, "type": "text"},
    {"part": {"reason": "stop", "type": "step-finish"}, "sessionID": session, "type": "step_finish"},
):
    print(json.dumps(event, separators=(",", ":")), flush=True)
""",
        encoding="utf-8",
    )
    path.chmod(0o555)
    return path


def _install_fake_condition(
    monkeypatch: pytest.MonkeyPatch,
    artifact: Path,
) -> Path:
    archive = artifact.with_name("opencode-linux-x64.tar.gz")
    archive.write_bytes(b"sealed archive")
    archive.chmod(0o444)
    artifact_data = artifact.read_bytes()
    artifact_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact_data))
    archive_identity = str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, archive.read_bytes())
    )
    condition_identity = TypedDigest.from_bytes(
        DigestKind.FUNCTIONAL_V1_CONDITION,
        canonical_json_bytes({"artifact": artifact_identity}),
    )
    lock = {
        "adapter": {
            "configuration": {
                "archive_bytes": archive.stat().st_size,
                "archive_digest": archive_identity,
                "artifact_bytes": len(artifact_data),
                "launch_shim": {"digest": OPENCODE_SHIM_IDENTITY},
            }
        },
        "artifact": {"digest": artifact_identity},
    }
    monkeypatch.setattr(
        opencode_runtime,
        "load_opencode_condition_lock",
        lambda: (b"", lock, condition_identity),
    )
    return archive


def _run_trial(
    recording_provider: Any,
    tmp_path: Path,
    *,
    name: str,
    artifact: Path,
    archive: Path,
    unsupported: bool = False,
) -> tuple[Any, Any, Path, Path]:
    repository = tmp_path / f"source-{name}"
    repository.mkdir()
    (repository / "baseline.txt").write_text("sealed baseline\n", encoding="utf-8")
    if unsupported:
        (repository / "unsupported").write_text("true\n", encoding="utf-8")
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
        )
    )
    artifact_identity = str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact.read_bytes())
    )
    archive_identity = str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, archive.read_bytes())
    )
    provisioning = OpenCodeProvisioning(
        condition_identity=str(opencode_runtime.load_opencode_condition_lock()[2]),
        archive_path=archive,
        archive_identity=archive_identity,
        artifact_path=artifact,
        artifact_identity=artifact_identity,
        launch_shim_path=opencode_runtime.opencode_launch_shim_path(),
        launch_shim_identity=OPENCODE_SHIM_IDENTITY,
        manifest_path=tmp_path / "unused-provisioning.json",
    )
    trial_root = tmp_path / f"trial-{name}"
    with proxy:
        result = ConditionRunner().run(
            ConditionRunRequest(
                process=sealed_opencode_process(
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


def test_fresh_run_trials_preserve_stock_autonomy_and_complete_evidence(
    recording_provider: Any,
    tmp_path: Path,
    acceptance_observation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _fake_opencode(tmp_path)
    archive = _install_fake_condition(monkeypatch, artifact)
    first = _run_trial(
        recording_provider,
        tmp_path,
        name="one",
        artifact=artifact,
        archive=archive,
    )
    second = _run_trial(
        recording_provider,
        tmp_path,
        name="two",
        artifact=artifact,
        archive=archive,
    )

    assert len(recording_provider.requests) == 4
    for index, (result, snapshot, evidence_path, trial_root) in enumerate(
        (first, second)
    ):
        requests = recording_provider.requests[index * 2 : index * 2 + 2]
        bodies = [json.loads(request.body) for request in requests]
        observation = json.loads(
            (trial_root / "repository/opencode-observation.json").read_text(
                encoding="utf-8"
            )
        )
        task_brief = bodies[1]["messages"][-1]["content"].encode()
        qualification = evaluate_opencode_qualification(
            result,
            evidence_path,
            expected_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
            observed_brief_sha256="sha256:" + hashlib.sha256(task_brief).hexdigest(),
            workspace_verified=(
                observation["workspace"] == str(trial_root / "repository")
            ),
            unexpected_network_requests=0,
        )

        delivery = json.loads(
            (
                result.capture_root
                / "native/home/.model-benchmark/opencode-delivery.json"
            ).read_text(encoding="utf-8")
        )
        events = [
            json.loads(line)
            for line in (
                result.capture_root
                / "native/home/.model-benchmark/opencode-events.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert qualification.qualified is True
        assert qualification.reason_code == "qualified"
        assert qualification.evidence["provider_response_count"] == 2
        assert result.exit_code == 0
        assert result.signal is None
        assert result.process_tree_terminated is True
        assert result.infrastructure_valid is True
        assert result.environment_names == OPENCODE_ENVIRONMENT_NAMES
        assert "home/.model-benchmark/opencode-delivery.json" in result.artifact_digests
        assert "home/.model-benchmark/opencode-events.jsonl" in result.artifact_digests
        assert [event["type"] for event in events] == [
            "step_start",
            "text",
            "step_finish",
        ]
        assert delivery["auth_persistence"] is False
        assert delivery["brief_sha256"] == (
            "sha256:" + hashlib.sha256(_BRIEF).hexdigest()
        )
        assert "cleaned_generated_paths" not in delivery
        assert delivery["model"] == _MODEL
        assert delivery["provider"] == "model-benchmark-proxy"
        assert delivery["proxy_base_url"].startswith("http://127.0.0.1:")
        assert delivery["transport"] == "run-stdin-json-events"
        assert delivery["workspace"] == str(trial_root / "repository")
        assert (trial_root / "repository/generated.csv").read_text(
            encoding="utf-8"
        ) == "derived output"
        assert snapshot.request_count == 2
        assert snapshot.provider_tokens == 34
        assert snapshot.provider_cost_usd == "0.20"
        assert observation["brief"].encode() == _BRIEF
        assert observation["request_count"] == 2
        config = observation["config"]
        assert config["autoupdate"] is False
        assert config["mcp"] == {}
        assert config["plugin"] == []
        assert config["share"] == "disabled"
        provider = config["provider"]["model-benchmark-proxy"]
        assert provider["npm"] == "@ai-sdk/openai-compatible"
        assert provider["options"]["apiKey"] == "{env:MODEL_BENCHMARK_PROXY_TOKEN}"
        assert provider["options"]["baseURL"] == delivery["proxy_base_url"]
        assert list(provider["models"]) == [_MODEL]
        for request, body in zip(requests, bodies, strict=True):
            assert request.path == "/chat/completions"
            assert request.headers["authorization"] == f"Bearer {_REAL_KEY}"
            assert body["model"] == _MODEL
            assert body["messages"][-1]["content"].encode() == _BRIEF
        assert not (trial_root / "home/.local/share/opencode/auth.json").exists()
        assert (trial_root / "home/.opencode-fresh-home").is_file()
        for captured_path in result.capture_root.rglob("*"):
            if captured_path.is_file():
                captured = captured_path.read_bytes()
                assert _REAL_KEY.encode() not in captured
                token = "opaque-token-one" if index == 0 else "opaque-token-two"
                assert token.encode() not in captured

    acceptance_observation(
        "opencode-run-qualified",
        {
            "fresh_homes": 2,
            "provider_requests": len(recording_provider.requests),
            "requests_per_trial": 2,
            "route": "/chat/completions",
        },
    )


def test_unsupported_run_behavior_is_unqualified_without_fallback(
    recording_provider: Any,
    tmp_path: Path,
    acceptance_observation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _fake_opencode(tmp_path)
    archive = _install_fake_condition(monkeypatch, artifact)
    result, _, evidence_path, _ = _run_trial(
        recording_provider,
        tmp_path,
        name="unsupported",
        artifact=artifact,
        archive=archive,
        unsupported=True,
    )
    qualification = evaluate_opencode_qualification(
        result,
        evidence_path,
        expected_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
        observed_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
        workspace_verified=True,
        unexpected_network_requests=0,
    )

    assert qualification.qualified is False
    assert qualification.reason_code == "opencode-run-unsupported"
    assert result.exit_code == 78
    assert result.process_tree_terminated is True
    assert recording_provider.requests == []
    acceptance_observation(
        "unsupported-opencode-unqualified",
        {"fallback_attempts": 0, "reason_code": qualification.reason_code},
    )


@pytest.mark.parametrize(
    ("protocol", "npm"),
    [
        ("openai-chat-completions", "@ai-sdk/openai-compatible"),
        ("anthropic-messages", "@ai-sdk/anthropic"),
    ],
)
def test_launch_config_selects_the_declared_provider_protocol(
    protocol: str,
    npm: str,
) -> None:
    value = opencode_launch._provider_config(
        base_url="http://credential-proxy:8080",
        model=_MODEL,
        protocol=protocol,
    )

    provider = value["provider"]["model-benchmark-proxy"]
    assert provider["npm"] == npm
    assert provider["options"]["baseURL"] == ("http://credential-proxy:8080")
