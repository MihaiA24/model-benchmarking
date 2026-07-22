from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import model_benchmark.runtime.omp as omp_runtime
from model_benchmark.declarations.canonical import canonical_json_bytes, load_canonical_json
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.conditions import (
    ConditionAdapterError,
    ConditionRunRequest,
    ConditionRunner,
)
from model_benchmark.runtime.credential_proxy import CredentialProxy, CredentialProxyConfig
from model_benchmark.runtime.omp import (
    OMP_ARTIFACT_BYTES,
    OMP_ARTIFACT_IDENTITY,
    OMP_DIAGNOSTIC_EXCLUSIONS,
    OMP_ARTIFACT_URL,
    OMP_ENVIRONMENT_NAMES,
    OMP_SHIM_IDENTITY,
    OMP_VERSION,
    OmpProvisioning,
    evaluate_omp_qualification,
    load_omp_condition_lock,
    provision_omp,
    sealed_omp_process,
)


_REAL_KEY = "provider-secret-value"
_MODEL = "locked/model"
_BRIEF = b"Implement the exact locked behavior.\n"


def test_condition_lock_seals_the_exact_stock_omp_profile(
    acceptance_observation: Any,
) -> None:
    data, lock, identity = load_omp_condition_lock()

    assert canonical_json_bytes(dict(lock)) == data
    assert lock["artifact"] == {
        "digest": OMP_ARTIFACT_IDENTITY,
        "kind": "native-executable",
        "platform": "linux/amd64",
    }
    adapter = lock["adapter"]
    assert isinstance(adapter, dict)
    assert adapter["non_interactive"] is True
    assert adapter["self_update"] is False
    assert adapter["environment_names"] == list(OMP_ENVIRONMENT_NAMES)
    configuration = adapter["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["artifact_bytes"] == OMP_ARTIFACT_BYTES
    assert configuration["artifact_source"] == OMP_ARTIFACT_URL
    assert configuration["artifact_version"] == OMP_VERSION
    assert configuration["diagnostic_exclusions"] == dict(OMP_DIAGNOSTIC_EXCLUSIONS)
    assert configuration["runtime_installation"] is False
    assert configuration["session_persistence"] is False
    assert configuration["instruction_transport"] == "rpc-prompt-jsonl"
    assert configuration["launch_shim"]["digest"] == OMP_SHIM_IDENTITY
    assert configuration["models_yml"] == {
        "providers": {
            "model-benchmark-proxy": {
                "api": "openai-completions",
                "apiKey": "MODEL_BENCHMARK_PROXY_TOKEN",
                "authHeader": True,
                "baseUrl": "manifest-provider-base-url",
                "models": [
                    {
                        "id": "manifest-provider-model",
                        "name": "manifest-provider-model",
                    }
                ],
            }
        }
    }
    acceptance_observation(
        "sealed-omp-identities",
        {
            "artifact": OMP_ARTIFACT_IDENTITY,
            "condition": str(identity),
            "launch_shim": OMP_SHIM_IDENTITY,
        },
    )


def test_provision_is_digest_first_and_warm_preflight_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acceptance_observation: Any,
) -> None:
    artifact = b"#!/bin/sh\nexit 0\n"
    artifact_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact))
    artifact_url = "https://artifacts.example/omp-v16.4.0-linux-x64"
    _, original, _ = load_omp_condition_lock()
    lock = json.loads(json.dumps(dict(original)))
    lock["artifact"]["digest"] = artifact_identity
    lock["adapter"]["configuration"]["artifact_bytes"] = len(artifact)
    lock["adapter"]["configuration"]["artifact_source"] = artifact_url
    lock_bytes = canonical_json_bytes(lock)
    lock_path = tmp_path / "omp.condition.json"
    lock_path.write_bytes(lock_bytes)

    monkeypatch.setattr(omp_runtime, "OMP_ARTIFACT_IDENTITY", artifact_identity)
    monkeypatch.setattr(omp_runtime, "OMP_ARTIFACT_BYTES", len(artifact))
    monkeypatch.setattr(omp_runtime, "OMP_ARTIFACT_URL", artifact_url)
    monkeypatch.setattr(omp_runtime, "omp_condition_lock_path", lambda: lock_path)
    calls: list[str] = []

    def open_artifact(url: str, *, timeout: int) -> io.BytesIO:
        assert timeout == 120
        calls.append(url)
        return io.BytesIO(artifact)

    monkeypatch.setattr(omp_runtime.urllib.request, "urlopen", open_artifact)
    cache = tmp_path / "cache"
    cold = provision_omp(cache, lock_bytes)
    before = {
        path: (path.stat().st_mtime_ns, path.stat().st_mode)
        for path in (cold.artifact_path, cold.launch_shim_path, cold.manifest_path)
    }
    warm = provision_omp(cache, lock_bytes)
    after = {
        path: (path.stat().st_mtime_ns, path.stat().st_mode)
        for path in (warm.artifact_path, warm.launch_shim_path, warm.manifest_path)
    }

    assert calls == [artifact_url]
    assert cold == warm
    assert before == after
    assert stat.S_IMODE(cold.artifact_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(cold.launch_shim_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(cold.manifest_path.stat().st_mode) == 0o400
    manifest = load_canonical_json(cold.manifest_path.read_bytes())
    assert manifest["network"] == "provision-only"
    acceptance_observation(
        "digest-first-warm-preflight",
        {"download_count": len(calls), "read_only": before == after},
    )

    cold.artifact_path.chmod(0o755)
    cold.artifact_path.write_bytes(b"changed")
    with pytest.raises(ConditionAdapterError, match="cached executable") as captured:
        omp_runtime.preflight_omp(cache, lock_bytes)
    assert captured.value.reason_code == "condition-unqualified"


def _fake_omp(tmp_path: Path) -> Path:
    path = tmp_path / "omp"
    path.write_text(
        f"""#!{sys.executable}
import http.client
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

home = Path(os.environ["HOME"])
marker = home / ".omp-fresh-home"
if marker.exists():
    raise SystemExit(91)
marker.write_text("one trial", encoding="utf-8")
arguments = sys.argv[1:]
if arguments != ["--mode", "rpc", "--model", "model-benchmark-proxy/locked/model"]:
    raise SystemExit(92)
config = json.loads((home / ".omp/agent/models.yml").read_text(encoding="utf-8"))
provider = config["providers"]["model-benchmark-proxy"]
print(json.dumps({{"type": "ready"}}, separators=(",", ":")), flush=True)
command = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
if (Path.cwd() / "unsupported").exists():
    print(json.dumps({{"id": "approval", "method": "confirm", "type": "extension_ui_request"}}, separators=(",", ":")), flush=True)
    time.sleep(10)
    raise SystemExit(93)
body = json.dumps({{
    "messages": [{{"content": command["message"], "role": "user"}}],
    "model": provider["models"][0]["id"],
}}, separators=(",", ":")).encode()
parsed = urlsplit(provider["baseUrl"])
connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
connection.request(
    "POST",
    f"{{parsed.path}}/chat/completions",
    body=body,
    headers={{
        "Authorization": f"Bearer {{os.environ[provider['apiKey']]}}",
        "Content-Type": "application/json",
    }},
)
response = connection.getresponse()
response.read()
if response.status != 200:
    raise SystemExit(94)
connection.close()
(Path.cwd() / "omp-observation.json").write_text(json.dumps({{
    "brief": command["message"],
    "provider": provider,
    "workspace": str(Path.cwd()),
}}, sort_keys=True), encoding="utf-8")
print(json.dumps({{
    "command": "prompt",
    "data": {{"agentInvoked": True}},
    "id": "functional-v1-prompt",
    "success": True,
    "type": "response",
}}, separators=(",", ":")), flush=True)
print(json.dumps({{"type": "agent_start"}}, separators=(",", ":")), flush=True)
print(json.dumps({{"messages": [], "type": "agent_end"}}, separators=(",", ":")), flush=True)
if sys.stdin.buffer.read():
    raise SystemExit(95)
""",
        encoding="utf-8",
    )
    path.chmod(0o555)
    return path


def _install_fake_condition(
    monkeypatch: pytest.MonkeyPatch,
    artifact: Path,
) -> None:
    artifact_data = artifact.read_bytes()
    artifact_identity = str(
        TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact_data)
    )
    condition_identity = TypedDigest.from_bytes(
        DigestKind.FUNCTIONAL_V1_CONDITION,
        canonical_json_bytes({"artifact": artifact_identity}),
    )
    lock = {
        "adapter": {
            "configuration": {
                "artifact_bytes": len(artifact_data),
                "launch_shim": {"digest": OMP_SHIM_IDENTITY},
            }
        },
        "artifact": {"digest": artifact_identity},
    }
    monkeypatch.setattr(
        omp_runtime,
        "load_omp_condition_lock",
        lambda: (b"", lock, condition_identity),
    )


def _run_trial(
    recording_provider: Any,
    tmp_path: Path,
    *,
    name: str,
    artifact: Path,
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
    artifact_identity = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact.read_bytes()))
    provisioning = OmpProvisioning(
        condition_identity=str(omp_runtime.load_omp_condition_lock()[2]),
        artifact_path=artifact,
        artifact_identity=artifact_identity,
        launch_shim_path=omp_runtime.omp_launch_shim_path(),
        launch_shim_identity=OMP_SHIM_IDENTITY,
        manifest_path=tmp_path / "unused-provisioning.json",
    )
    trial_root = tmp_path / f"trial-{name}"
    with proxy:
        result = ConditionRunner().run(
            ConditionRunRequest(
                process=sealed_omp_process(
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


def test_fresh_rpc_trials_preserve_stock_transport_and_complete_evidence(
    recording_provider: Any,
    tmp_path: Path,
    acceptance_observation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _fake_omp(tmp_path)
    _install_fake_condition(monkeypatch, artifact)
    first = _run_trial(recording_provider, tmp_path, name="one", artifact=artifact)
    second = _run_trial(recording_provider, tmp_path, name="two", artifact=artifact)

    assert len(recording_provider.requests) == 2
    for index, (result, snapshot, evidence_path, trial_root) in enumerate(
        (first, second)
    ):
        request = recording_provider.requests[index]
        body = json.loads(request.body)
        observation = json.loads(
            (trial_root / "repository/omp-observation.json").read_text(encoding="utf-8")
        )
        observed_brief = body["messages"][0]["content"].encode()
        qualification = evaluate_omp_qualification(
            result,
            evidence_path,
            expected_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
            observed_brief_sha256="sha256:" + hashlib.sha256(observed_brief).hexdigest(),
            workspace_verified=(
                observation["workspace"] == str(trial_root / "repository")
            ),
            unexpected_network_requests=0,
        )

        delivery = json.loads(
            (
                result.capture_root
                / "native/home/.model-benchmark/omp-delivery.json"
            ).read_text(encoding="utf-8")
        )
        assert qualification.qualified is True
        assert qualification.reason_code == "qualified"
        assert result.exit_code == 0
        assert result.signal is None
        assert result.process_tree_terminated is True
        assert result.infrastructure_valid is True
        assert result.environment_names == OMP_ENVIRONMENT_NAMES
        assert "home/.model-benchmark/omp-rpc.jsonl" in result.artifact_digests
        assert "home/.model-benchmark/omp-delivery.json" in result.artifact_digests
        assert delivery["brief_sha256"] == (
            "sha256:" + hashlib.sha256(_BRIEF).hexdigest()
        )
        assert delivery["model"] == _MODEL
        assert delivery["provider"] == "model-benchmark-proxy"
        assert delivery["proxy_base_url"] == observation["provider"]["baseUrl"]
        assert delivery["transport"] == "rpc-prompt-jsonl"
        assert delivery["workspace"] == str(trial_root / "repository")
        assert snapshot.request_count == 1
        assert snapshot.provider_tokens == 17
        assert snapshot.provider_cost_usd == "0.10"
        assert request.path == "/chat/completions"
        assert request.headers["authorization"] == f"Bearer {_REAL_KEY}"
        assert body["model"] == _MODEL
        assert observed_brief == _BRIEF
        assert observation["provider"]["api"] == "openai-completions"
        assert observation["provider"]["authHeader"] is True
        assert (trial_root / "home/.omp-fresh-home").is_file()
        for path in result.capture_root.rglob("*"):
            if path.is_file():
                captured = path.read_bytes()
                assert _REAL_KEY.encode() not in captured
                token = "opaque-token-one" if index == 0 else "opaque-token-two"
                assert token.encode() not in captured

    acceptance_observation(
        "omp-rpc-qualified",
        {
            "fresh_homes": 2,
            "provider_requests": len(recording_provider.requests),
            "route": "/chat/completions",
        },
    )


def test_unsupported_rpc_behavior_is_unqualified_without_fallback(
    recording_provider: Any,
    tmp_path: Path,
    acceptance_observation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _fake_omp(tmp_path)
    _install_fake_condition(monkeypatch, artifact)
    result, _, evidence_path, _ = _run_trial(
        recording_provider,
        tmp_path,
        name="unsupported",
        artifact=artifact,
        unsupported=True,
    )
    qualification = evaluate_omp_qualification(
        result,
        evidence_path,
        expected_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
        observed_brief_sha256="sha256:" + hashlib.sha256(_BRIEF).hexdigest(),
        workspace_verified=True,
        unexpected_network_requests=0,
    )

    assert qualification.qualified is False
    assert qualification.reason_code == "omp-rpc-unsupported"
    assert result.exit_code == 78
    assert result.process_tree_terminated is True
    assert recording_provider.requests == []
    acceptance_observation(
        "unsupported-omp-unqualified",
        {"fallback_attempts": 0, "reason_code": qualification.reason_code},
    )
