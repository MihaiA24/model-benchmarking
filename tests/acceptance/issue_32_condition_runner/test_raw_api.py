from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from model_benchmark.runtime.credential_proxy import CredentialProxy, CredentialProxyConfig
from model_benchmark.runtime.raw_api import RawApiMaterializer, RawApiRequest


_MODEL = "locked/model"
_REAL_KEY = "provider-secret-value"
_TRIAL_TOKEN = "opaque-trial-token"
_TARGET = "src/answer.py"


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


def _provider_envelope(content: str | None, *, refusal: str | None = None) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {
                    "content": content,
                    "refusal": refusal,
                    "role": "assistant",
                },
            }
        ],
        "model": _MODEL,
        "usage": {"cost_usd": "0.10", "total_tokens": 23},
    }


def _sse_stream(
    content: str | None,
    *,
    refusal: str | None = None,
    chunk_size: int = 7,
    done: bool = True,
) -> bytes:
    # The materializer streams its one request (issue #99): replay the
    # OpenAI-compatible SSE shape the provider emits for it.
    events: list[dict[str, object]] = [
        {"choices": [{"delta": {"role": "assistant"}, "index": 0}], "model": _MODEL}
    ]
    if refusal is not None:
        events.append(
            {"choices": [{"delta": {"refusal": refusal}, "index": 0}], "model": _MODEL}
        )
    if content is not None:
        for start in range(0, len(content), chunk_size):
            events.append(
                {
                    "choices": [
                        {"delta": {"content": content[start : start + chunk_size]}, "index": 0}
                    ],
                    "model": _MODEL,
                }
            )
    events.append({"choices": [], "model": _MODEL, "usage": {"cost_usd": "0.10", "total_tokens": 23}})
    body = b"".join(
        b"data: " + json.dumps(event, separators=(",", ":")).encode() + b"\n\n"
        for event in events
    )
    if done:
        body += b"data: [DONE]\n\n"
    return body


def _enqueue_stream(provider: Any, content: str | None, *, refusal: str | None = None) -> None:
    provider.enqueue_bytes(_sse_stream(content, refusal=refusal), content_type="text/event-stream")


def _request(proxy: CredentialProxy, repository: Path, *, max_bytes: int = 128) -> RawApiRequest:
    return RawApiRequest(
        proxy_base_url=proxy.base_url,
        proxy_token=_TRIAL_TOKEN,
        model=_MODEL,
        developer_brief=b"Replace the locked target with the requested implementation.\n",
        repository=repository,
        target_path=_TARGET,
        max_content_bytes=max_bytes,
    )


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / _TARGET).write_text("before\n", encoding="utf-8")
    (repository / "unchanged.txt").write_text("stable\n", encoding="utf-8")
    return repository


def test_raw_api_makes_one_request_and_atomically_changes_only_locked_file(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    replacement = {"content": "print('after')\n", "path": _TARGET}
    _enqueue_stream(recording_provider, json.dumps(replacement))
    repository = _repository(tmp_path)

    with _proxy(recording_provider, tmp_path) as proxy:
        result = RawApiMaterializer().materialize(_request(proxy, repository))

    assert result.outcome == "ready-for-capture"
    assert result.reason_code == "materialized"
    assert result.request_count == 1
    assert result.materialized_path == _TARGET
    assert result.final_repository is not None
    assert result.final_repository.condition == "raw-api"
    assert result.final_repository.repository == repository
    assert (repository / _TARGET).read_text(encoding="utf-8") == "print('after')\n"
    assert (repository / "unchanged.txt").read_text(encoding="utf-8") == "stable\n"
    assert sorted(path.relative_to(repository).as_posix() for path in repository.rglob("*") if path.is_file()) == [
        "src/answer.py",
        "unchanged.txt",
    ]
    assert len(recording_provider.requests) == 1
    provider_request = recording_provider.requests[0]
    request_value = json.loads(provider_request.body)
    assert request_value["messages"][0] == {
        "content": "Replace the locked target with the requested implementation.\n",
        "role": "user",
    }
    assert request_value["stream"] is True
    assert provider_request.headers["authorization"] == f"Bearer {_REAL_KEY}"
    # The materializer's own UA must survive the proxy unmodified: UA-less
    # upstream traffic is tarpitted by the provider's WAF (issue #99).
    assert provider_request.headers["user-agent"] == "model-benchmark-raw-api/1"


@pytest.mark.parametrize(
    ("content", "reason_code", "max_bytes"),
    [
        ("not json", "invalid-provider-json", 128),
        (json.dumps({"content": "after", "extra": True, "path": _TARGET}), "invalid-materialization-envelope", 128),
        (json.dumps({"content": "after", "path": "src/wrong.py"}), "response-path-mismatch", 128),
        (json.dumps({"content": "x" * 129, "path": _TARGET}), "content-size-limit", 128),
        ('{"path":"src/answer.py","content":"a","path":"src/answer.py"}', "duplicate-json-field", 128),
        (json.dumps({"content": "\ud800", "path": _TARGET}), "invalid-content-encoding", 128),
    ],
)
def test_invalid_raw_api_envelope_is_terminal_without_retry(
    recording_provider: Any,
    tmp_path: Path,
    content: str,
    reason_code: str,
    max_bytes: int,
) -> None:
    _enqueue_stream(recording_provider, content)
    repository = _repository(tmp_path)

    with _proxy(recording_provider, tmp_path) as proxy:
        result = RawApiMaterializer().materialize(
            _request(proxy, repository, max_bytes=max_bytes)
        )

    assert result.outcome == "valid_harness_outcome"
    assert result.reason_code == reason_code
    assert result.request_count == 1
    assert result.materialized_path is None
    assert result.final_repository is None
    assert (repository / _TARGET).read_text(encoding="utf-8") == "before\n"
    assert len(recording_provider.requests) == 1


def test_provider_refusal_and_failure_are_terminal_without_retry(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    _enqueue_stream(recording_provider, None, refusal="cannot comply")
    repository = _repository(tmp_path)

    with _proxy(recording_provider, tmp_path) as proxy:
        refusal = RawApiMaterializer().materialize(_request(proxy, repository))

    assert refusal.outcome == "valid_harness_outcome"
    assert refusal.reason_code == "provider-refusal"
    assert len(recording_provider.requests) == 1

    failure_root = tmp_path / "failure"
    failure_root.mkdir()
    failed_repository = _repository(failure_root)
    recording_provider.enqueue_json({"error": "unavailable"}, status=503)
    with _proxy(recording_provider, failure_root) as proxy:
        failure = RawApiMaterializer().materialize(_request(proxy, failed_repository))

    assert failure.outcome == "valid_harness_outcome"
    assert failure.reason_code == "provider-failure"
    assert len(recording_provider.requests) == 2


def test_non_streamed_json_response_still_materializes(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    # An upstream that ignores stream=true and answers with one JSON body
    # must keep working: the decoder falls back on the non-SSE shape.
    replacement = {"content": "print('after')\n", "path": _TARGET}
    recording_provider.enqueue_json(_provider_envelope(json.dumps(replacement)))
    repository = _repository(tmp_path)

    with _proxy(recording_provider, tmp_path) as proxy:
        result = RawApiMaterializer().materialize(_request(proxy, repository))

    assert result.outcome == "ready-for-capture"
    assert (repository / _TARGET).read_text(encoding="utf-8") == "print('after')\n"


def test_truncated_stream_without_done_is_invalid_provider_json(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    replacement = {"content": "print('after')\n", "path": _TARGET}
    recording_provider.enqueue_bytes(
        _sse_stream(json.dumps(replacement), done=False),
        content_type="text/event-stream",
    )
    repository = _repository(tmp_path)

    with _proxy(recording_provider, tmp_path) as proxy:
        result = RawApiMaterializer().materialize(_request(proxy, repository))

    assert result.outcome == "valid_harness_outcome"
    assert result.reason_code == "invalid-provider-envelope"
    assert (repository / _TARGET).read_text(encoding="utf-8") == "before\n"


def test_connect_retries_absorb_a_late_proxy_route_without_extra_requests(
    recording_provider: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The cell's proxy route can lag behind the main container (issue #99:
    # concurrent compose churn). The local TCP connect retries within a
    # bounded window; the provider still sees exactly one request.
    import http.client

    from model_benchmark.runtime import raw_api

    monkeypatch.setattr(raw_api, "_CONNECT_RETRY_DELAY_SECONDS", 0.05)
    replacement = {"content": "print('after')\n", "path": _TARGET}
    _enqueue_stream(recording_provider, json.dumps(replacement))
    repository = _repository(tmp_path)

    with _proxy(recording_provider, tmp_path) as proxy:
        real_connect = http.client.HTTPConnection.connect
        refusals = {"remaining": 3}

        def _flaky_connect(self: http.client.HTTPConnection) -> None:
            if refusals["remaining"] > 0:
                refusals["remaining"] -= 1
                raise ConnectionRefusedError("route not ready")
            real_connect(self)

        monkeypatch.setattr(http.client.HTTPConnection, "connect", _flaky_connect)
        result = RawApiMaterializer().materialize(_request(proxy, repository))

    assert refusals["remaining"] == 0
    assert result.outcome == "ready-for-capture"
    assert result.reason_code == "materialized"
    assert result.request_count == 1
    assert len(recording_provider.requests) == 1
    assert (repository / _TARGET).read_text(encoding="utf-8") == "print('after')\n"


def test_connect_retry_window_is_bounded_and_carries_no_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    from model_benchmark.runtime import raw_api

    monkeypatch.setattr(raw_api, "_CONNECT_RETRY_SECONDS", 0.2)
    monkeypatch.setattr(raw_api, "_CONNECT_RETRY_DELAY_SECONDS", 0.05)
    # A bound-but-not-listening socket refuses every connect deterministically.
    with socket.socket() as blocked:
        blocked.bind(("127.0.0.1", 0))
        port = blocked.getsockname()[1]
        repository = _repository(tmp_path)
        result = RawApiMaterializer().materialize(
            RawApiRequest(
                proxy_base_url=f"http://127.0.0.1:{port}",
                proxy_token=_TRIAL_TOKEN,
                model=_MODEL,
                developer_brief=b"brief\n",
                repository=repository,
                target_path=_TARGET,
                max_content_bytes=128,
            )
        )

    assert result.outcome == "valid_harness_outcome"
    assert result.reason_code == "provider-failure"
    assert (repository / _TARGET).read_text(encoding="utf-8") == "before\n"
