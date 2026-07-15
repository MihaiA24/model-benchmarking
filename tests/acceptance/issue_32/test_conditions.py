from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import model_benchmark.runtime.conditions as condition_runtime
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.runtime.conditions import (
    ConditionRunRequest,
    ConditionRunner,
    SealedConditionProcess,
)
from model_benchmark.runtime.credential_proxy import CredentialProxy, CredentialProxyConfig


_MODEL = "locked/model"
_REAL_KEY = "provider-secret-value"
_TRIAL_TOKEN = "opaque-trial-token"
_BRIEF = b"Implement the exact locked behavior.\n"


def _provider_response() -> dict[str, object]:
    return {
        "choices": [{"message": {"content": "ok"}}],
        "model": _MODEL,
        "usage": {"cost_usd": "0.10", "total_tokens": 17},
    }


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "sealed-harness"
    path.write_text(
        f"""#!{sys.executable}
import http.client
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

brief = sys.stdin.buffer.read()
home = Path(os.environ["HOME"])
marker = home / "fresh-state-marker"
if marker.exists():
    raise SystemExit(91)
marker.write_text("owned by one Trial", encoding="utf-8")
parsed = urlsplit(os.environ["PROXY_BASE_URL"])
body = json.dumps({{
    "messages": [{{"content": brief.decode("utf-8"), "role": "user"}}],
    "model": os.environ["PROVIDER_MODEL"],
}}, separators=(",", ":")).encode()
connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
connection.request(
    "POST",
    f"{{parsed.path}}/chat/completions",
    body=body,
    headers={{
        "Authorization": f"Bearer {{os.environ['MODEL_BENCHMARK_PROXY_TOKEN']}}",
        "Content-Type": "application/json",
    }},
)
response = connection.getresponse()
response.read()
if response.status != 200:
    raise SystemExit(92)
connection.close()
(home / "native.json").write_text(json.dumps({{
    "brief_sha256_input": brief.decode("utf-8"),
    "environment_names": sorted(os.environ),
}}, sort_keys=True), encoding="utf-8")
if sys.argv[1:] == ["leak"]:
    print(os.environ["MODEL_BENCHMARK_PROXY_TOKEN"])
elif sys.argv[1:] == ["sleep"]:
    time.sleep(60)
else:
    print("harness completed")
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _proxy(recording_provider: Any, tmp_path: Path) -> CredentialProxy:
    return CredentialProxy(
        CredentialProxyConfig(
            upstream_base_url=recording_provider.base_url,
            model=_MODEL,
            real_api_key=_REAL_KEY,
            trial_token=_TRIAL_TOKEN,
            provider_tokens_per_trial=100_000,
            stop_after_cost_usd_per_trial=Decimal("5.00"),
            evidence_path=tmp_path / "proxy-events.jsonl",
        )
    )


def _request(
    condition: str,
    artifact: Path,
    repository: Path,
    trial_root: Path,
    proxy: CredentialProxy,
    *,
    arguments: tuple[str, ...] = (),
) -> ConditionRunRequest:
    identity = TypedDigest.from_bytes(DigestKind.ARTIFACT, artifact.read_bytes())
    return ConditionRunRequest(
        process=SealedConditionProcess(
            condition=condition,
            artifact_path=artifact,
            artifact_identity=str(identity),
            arguments=arguments,
            environment={
                "MODEL_BENCHMARK_PROXY_TOKEN": _TRIAL_TOKEN,
                "PROVIDER_MODEL": _MODEL,
                "PROXY_BASE_URL": proxy.base_url,
            },
            native_artifact_paths=("home/native.json",),
        ),
        repository_source=repository,
        trial_root=trial_root,
        developer_brief=_BRIEF,
        trial_proxy_token=_TRIAL_TOKEN,
        sensitive_values=(_REAL_KEY, _TRIAL_TOKEN),
    )


@pytest.mark.parametrize("condition", ["omp", "opencode", "hermes"])
def test_three_harness_shapes_use_one_isolated_process_boundary_and_recording_provider(
    recording_provider: Any,
    tmp_path: Path,
    condition: str,
) -> None:
    recording_provider.enqueue_json(_provider_response())
    artifact = _script(tmp_path)
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "input.txt").write_text("sealed baseline\n", encoding="utf-8")

    with _proxy(recording_provider, tmp_path) as proxy:
        result = ConditionRunner().run(
            _request(
                condition,
                artifact,
                repository,
                tmp_path / f"trial-{condition}",
                proxy,
            )
        )

    assert result.exit_code == 0
    assert result.signal is None
    assert result.reason_code == "process-exited"
    assert result.infrastructure_valid is True
    assert result.process_tree_terminated is True
    assert result.environment_names == (
        "MODEL_BENCHMARK_PROXY_TOKEN",
        "PROVIDER_MODEL",
        "PROXY_BASE_URL",
    )
    assert result.capture_root.name == "capture"
    assert result.final_repository is not None
    assert result.final_repository.condition == condition
    assert result.final_repository.repository == tmp_path / f"trial-{condition}/repository"
    assert (result.capture_root / "stdout.bin").read_bytes() == b"harness completed\n"
    native = json.loads((result.capture_root / "native/home/native.json").read_bytes())
    assert native["brief_sha256_input"] == _BRIEF.decode()
    assert "MODEL_BENCHMARK_PROVIDER_API_KEY" not in native["environment_names"]
    assert len(recording_provider.requests) == 1
    provider_body = json.loads(recording_provider.requests[0].body)
    assert provider_body["messages"] == [
        {"content": _BRIEF.decode(), "role": "user"}
    ]
    process_evidence = json.loads((result.capture_root / "process.json").read_bytes())
    assert "disposition" not in process_evidence
    assert "result_bundle_identity" not in process_evidence
    assert "score" not in process_evidence


def test_fresh_homes_share_no_mutable_harness_state(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    recording_provider.enqueue_json(_provider_response())
    recording_provider.enqueue_json(_provider_response())
    artifact = _script(tmp_path)
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "input.txt").write_text("sealed baseline\n", encoding="utf-8")

    with _proxy(recording_provider, tmp_path) as proxy:
        first = ConditionRunner().run(
            _request("omp", artifact, repository, tmp_path / "trial-one", proxy)
        )
        second = ConditionRunner().run(
            _request("omp", artifact, repository, tmp_path / "trial-two", proxy)
        )

    assert first.exit_code == second.exit_code == 0
    assert (tmp_path / "trial-one/home/fresh-state-marker").is_file()
    assert (tmp_path / "trial-two/home/fresh-state-marker").is_file()
    assert not (repository / "fresh-state-marker").exists()
    assert len(recording_provider.requests) == 2


def test_injected_secret_leak_is_invalid_infrastructure_and_capture_is_quarantined(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    recording_provider.enqueue_json(_provider_response())
    artifact = _script(tmp_path)
    repository = tmp_path / "source"
    repository.mkdir()

    with _proxy(recording_provider, tmp_path) as proxy:
        result = ConditionRunner().run(
            _request(
                "hermes",
                artifact,
                repository,
                tmp_path / "trial-leak",
                proxy,
                arguments=("leak",),
            )
        )

    assert result.infrastructure_valid is False
    assert result.reason_code == "secret-leak-detected"
    assert result.capture_root.name == "quarantine"
    assert (result.capture_root / "stdout.bin").read_bytes() == b"[REDACTED]\n"
    for path in result.capture_root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert _TRIAL_TOKEN.encode() not in data
            assert _REAL_KEY.encode() not in data


def test_wall_time_limit_terminates_the_process_group_and_preserves_capture_handoff(
    recording_provider: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_provider.enqueue_json(_provider_response())
    artifact = _script(tmp_path)
    repository = tmp_path / "source"
    repository.mkdir()
    monkeypatch.setattr(condition_runtime, "WALL_TIME_SECONDS", 1.0)
    monkeypatch.setattr(condition_runtime, "_SHUTDOWN_GRACE_SECONDS", 0.05)

    with _proxy(recording_provider, tmp_path) as proxy:
        result = ConditionRunner().run(
            _request(
                "opencode",
                artifact,
                repository,
                tmp_path / "trial-timeout",
                proxy,
                arguments=("sleep",),
            )
        )

    assert result.timed_out is True
    assert result.reason_code == "wall-time-limit"
    assert result.process_tree_terminated is True
    assert result.infrastructure_valid is True
    assert result.final_repository is not None


def test_changed_immutable_artifact_fails_before_process_or_provider_launch(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    artifact = _script(tmp_path)
    repository = tmp_path / "source"
    repository.mkdir()

    with _proxy(recording_provider, tmp_path) as proxy:
        request = _request(
            "omp",
            artifact,
            repository,
            tmp_path / "trial-corrupt-artifact",
            proxy,
        )
        artifact.write_text("changed after sealing", encoding="utf-8")
        result = ConditionRunner().run(request)

    assert result.infrastructure_valid is False
    assert result.reason_code == "artifact-verification-failed"
    assert result.final_repository is None
    assert recording_provider.requests == []
