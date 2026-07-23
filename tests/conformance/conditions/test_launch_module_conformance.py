"""Conformance seed for the Condition seam (issue #89, extended by issue #90).

Executes the digest-pinned raw-api launch module as a subprocess — the same
seam the condition image crosses — so drift between the module and the common
runtime interfaces (``RawApiRequest``/``RawApiResult``) fails here instead of
inside a live Trial Cell after provider spend.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from model_benchmark.declarations.canonical import load_canonical_json
from model_benchmark.declarations.provider_routes import PROVIDER_PROTOCOL_ENV
from model_benchmark.runtime.raw_api import (
    RawApiError,
    RawApiMaterializer,
    RawApiRequest,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MODULE_SOURCE_PATH = "model_benchmark/runtime/raw_api_launch.py"
_MODULE_PATH = _PROJECT_ROOT / "src" / _MODULE_SOURCE_PATH
_LOCK_PATH = _PROJECT_ROOT / "profiles/functional-v1/raw-api-v1.condition.json"
_MODEL = "locked/model"
_TOKEN = "opaque-trial-token"
_TARGET = "src/answer.py"
_BRIEF = b"Replace the locked target with the requested implementation.\n"


def _module_identity() -> str:
    digest = hashlib.sha256(_MODULE_PATH.read_bytes()).hexdigest()
    return f"artifact:sha256:{digest}"


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / _TARGET).write_text("before\n", encoding="utf-8")
    (repository / "unchanged.txt").write_text("stable\n", encoding="utf-8")
    return repository


def _run_launch_module(
    repository: Path,
    home: Path,
    base_url: str,
    *,
    artifact_identity: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "model_benchmark.runtime.raw_api_launch",
            "--artifact-identity",
            artifact_identity or _module_identity(),
            "--target-path",
            _TARGET,
        ],
        capture_output=True,
        check=False,
        cwd=repository,
        env={
            "HOME": str(home),
            "MODEL_BENCHMARK_PROVIDER_MODEL": _MODEL,
            PROVIDER_PROTOCOL_ENV: "openai-chat-completions",
            "MODEL_BENCHMARK_PROXY_BASE_URL": base_url,
            "MODEL_BENCHMARK_PROXY_TOKEN": _TOKEN,
            "PATH": os.environ["PATH"],
        },
        input=_BRIEF,
        timeout=60,
    )


def _delivery(home: Path) -> dict[str, object]:
    data = (home / ".model-benchmark/raw-api-delivery.json").read_text(encoding="utf-8")
    value = json.loads(data)
    assert isinstance(value, dict)
    return value


def test_launch_module_materializes_and_seals_delivery_evidence(
    provider: tuple[str, object], tmp_path: Path
) -> None:
    base_url, script = provider
    script.enqueue_envelope(path=_TARGET, content="print('after')\n")
    repository = _repository(tmp_path)
    home = tmp_path / "trial-home"
    home.mkdir()

    completed = _run_launch_module(repository, home, base_url)

    assert completed.returncode == 0, completed.stderr.decode()
    assert (repository / _TARGET).read_text(encoding="utf-8") == "print('after')\n"
    assert (repository / "unchanged.txt").read_text(encoding="utf-8") == "stable\n"
    assert _delivery(home) == {
        "artifact_identity": _module_identity(),
        "brief_sha256": f"sha256:{hashlib.sha256(_BRIEF).hexdigest()}",
        "diagnostic_code": None,
        "outcome": "ready-for-capture",
        "provider_model": _MODEL,
        "proxy_base_url": base_url,
        "reason_code": "materialized",
        "request_count": 1,
        "schema_version": 1,
        "target_path": _TARGET,
    }
    (request,) = script.requests
    assert request["path"] == "/chat/completions"
    assert request["authorization"] == f"Bearer {_TOKEN}"
    body = request["body"]
    assert isinstance(body, dict)
    assert body["model"] == _MODEL
    assert body["stream"] is True
    messages = body["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1] == {"content": _BRIEF.decode(), "role": "user"}
    assert messages[2]["role"] == "user"
    assert json.loads(messages[2]["content"]) == {
        "content": "before\n",
        "path": _TARGET,
    }


def test_launch_module_reports_provider_failure_without_materializing(
    provider: tuple[str, object], tmp_path: Path
) -> None:
    base_url, script = provider
    script.enqueue_failure(500)
    repository = _repository(tmp_path)
    home = tmp_path / "trial-home"
    home.mkdir()

    completed = _run_launch_module(repository, home, base_url)

    assert completed.returncode == 78, completed.stderr.decode()
    assert (repository / _TARGET).read_text(encoding="utf-8") == "before\n"
    delivery = _delivery(home)
    assert delivery["outcome"] == "valid_harness_outcome"
    assert delivery["reason_code"] == "provider-failure"
    assert delivery["request_count"] == 1


def test_launch_module_rejects_identity_mismatch_before_any_request(
    provider: tuple[str, object], tmp_path: Path
) -> None:
    base_url, script = provider
    repository = _repository(tmp_path)
    home = tmp_path / "trial-home"
    home.mkdir()
    wrong = f"artifact:sha256:{'0' * 64}"

    completed = _run_launch_module(repository, home, base_url, artifact_identity=wrong)

    assert completed.returncode == 78
    assert not (home / ".model-benchmark/raw-api-delivery.json").exists()
    assert (repository / _TARGET).read_text(encoding="utf-8") == "before\n"
    assert script.requests == []


def test_committed_condition_lock_pins_current_launch_module() -> None:
    lock = load_canonical_json(_LOCK_PATH.read_bytes())
    assert isinstance(lock, dict)
    adapter = lock["adapter"]
    assert isinstance(adapter, dict)
    configuration = adapter["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["launch_module"] == {
        "digest": _module_identity(),
        "source_path": _MODULE_SOURCE_PATH,
    }
    assert configuration["request_context"] == {
        "additional_files": 0,
        "developer_brief": "exact",
        "target_file": "exact-scenario-baseline-utf8",
    }
    artifact = lock["artifact"]
    assert isinstance(artifact, dict)
    assert artifact["digest"] == _module_identity()


def test_materializer_accepts_the_sealed_in_mesh_proxy_route(
    provider: tuple[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live cell wiring (issue #99): http://credential-proxy:8080/<path>.

    The loopback fixtures never exercised the in-mesh hostname, so the
    loopback-only gate silently killed every live Raw API cell before its
    one provider request. Route the pinned hostname at the scripted
    provider and prove the full materialization path runs on it.
    """
    base_url, script = provider
    script.enqueue_envelope(path=_TARGET, content="print('after')\n")
    repository = _repository(tmp_path)
    port = urlsplit(base_url).port
    original_getaddrinfo = socket.getaddrinfo

    def _in_mesh_getaddrinfo(host: object, *arguments: object, **keywords: object):
        resolved = "127.0.0.1" if host == "credential-proxy" else host
        return original_getaddrinfo(resolved, *arguments, **keywords)

    monkeypatch.setattr(socket, "getaddrinfo", _in_mesh_getaddrinfo)

    result = RawApiMaterializer().materialize(
        RawApiRequest(
            proxy_base_url=f"http://credential-proxy:{port}/zen/go/v1",
            proxy_token=_TOKEN,
            model=_MODEL,
            developer_brief=_BRIEF,
            repository=repository,
            target_path=_TARGET,
            max_content_bytes=1 << 20,
        )
    )

    assert result.outcome == "ready-for-capture"
    assert result.request_count == 1
    assert result.materialized_path == _TARGET
    assert (repository / _TARGET).read_text(encoding="utf-8") == "print('after')\n"
    (request,) = script.requests
    assert request["path"] == "/zen/go/v1/chat/completions"


@pytest.mark.parametrize(
    "proxy_base_url",
    [
        "https://credential-proxy:8080/zen/go/v1",
        "http://provider.example.com/v1",
        "http://user@credential-proxy:8080/v1",
        "http://credential-proxy:8080/v1?redirect=1",
        "http://credential-proxy:8080/v1#fragment",
    ],
)
def test_request_validation_still_rejects_non_proxy_routes(
    proxy_base_url: str, tmp_path: Path
) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(RawApiError):
        RawApiRequest(
            proxy_base_url=proxy_base_url,
            proxy_token=_TOKEN,
            model=_MODEL,
            developer_brief=_BRIEF,
            repository=repository,
            target_path=_TARGET,
            max_content_bytes=1 << 20,
        )
