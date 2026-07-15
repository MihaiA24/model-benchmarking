from __future__ import annotations

import http.client
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from model_benchmark.runtime.credential_proxy import (
    CredentialProxy,
    CredentialProxyConfig,
)



_MODEL = "locked/model"
_REAL_KEY = "provider-secret-value"
_TRIAL_TOKEN = "opaque-trial-token"


def _proxy(
    provider: Any,
    tmp_path: Path,
    *,
    tokens: int = 100_000,
    cost: str = "5.00",
) -> CredentialProxy:
    return CredentialProxy(
        CredentialProxyConfig(
            upstream_base_url=provider.base_url,
            model=_MODEL,
            real_api_key=_REAL_KEY,
            trial_token=_TRIAL_TOKEN,
            provider_tokens_per_trial=tokens,
            stop_after_cost_usd_per_trial=Decimal(cost),
            evidence_path=tmp_path / "proxy-events.jsonl",
        )
    )


def _post(
    proxy: CredentialProxy,
    body: bytes,
    *,
    path: str = "/chat/completions",
    token: str = _TRIAL_TOKEN,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    parsed = urlsplit(proxy.base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    selected_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    try:
        connection.request(
            "POST",
            f"{parsed.path}{path}",
            body=body,
            headers=selected_headers,
        )
        response = connection.getresponse()
        result = response.status, response.read()
        response.close()
        return result
    finally:
        connection.close()


def _request_body(model: str = _MODEL) -> bytes:
    return json.dumps(
        {
            "messages": [{"content": "private prompt bytes", "role": "user"}],
            "model": model,
            "stream": True,
        },
        separators=(",", ":"),
    ).encode()


def test_auth_replacement_and_streaming_preserve_bytes_and_observe_native_retries(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    stream = (
        b'data: {"choices":[{"delta":{"content":"alpha"}}],"model":"locked/model"}\n\n'
        b'data: {"choices":[],"model":"locked/model","usage":{"cost_usd":"0.25",'
        b'"total_tokens":11}}\n\ndata: [DONE]\n\n'
    )
    recording_provider.enqueue_bytes(
        stream,
        content_type="text/event-stream",
        chunks=(1, 7, 13, 2, 31),
    )
    recording_provider.enqueue_bytes(
        stream,
        content_type="text/event-stream",
        chunks=(1, 7, 13, 2, 31),
    )
    request_body = _request_body()

    with _proxy(recording_provider, tmp_path) as proxy:
        first = _post(proxy, request_body)
        second = _post(proxy, request_body)

    assert first == (200, stream)
    assert second == (200, stream)
    assert len(recording_provider.requests) == 2
    assert all(request.body == request_body for request in recording_provider.requests)
    assert all(request.path == "/v1/chat/completions" for request in recording_provider.requests)
    assert all(
        request.headers["authorization"] == f"Bearer {_REAL_KEY}"
        for request in recording_provider.requests
    )
    evidence = (tmp_path / "proxy-events.jsonl").read_bytes()
    assert evidence.count(b'"event":"provider-response"') == 2
    assert _REAL_KEY.encode() not in evidence
    assert _TRIAL_TOKEN.encode() not in evidence
    assert b"private prompt bytes" not in evidence


def test_route_model_and_auth_controls_fail_closed_before_provider(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    with _proxy(recording_provider, tmp_path) as proxy:
        assert _post(proxy, _request_body(), path="/responses")[0] == 404
        assert _post(proxy, _request_body(model="wrong/model"))[0] == 400
        assert _post(proxy, b'{"model":"locked/model","model":"wrong/model"}')[0] == 400
        assert _post(proxy, _request_body(), token="wrong-token")[0] == 401
        assert _post(
            proxy,
            _request_body(),
            headers={"X-Upstream-Url": "https://attacker.invalid/v1"},
        )[0] == 400

    assert recording_provider.requests == []
    evidence = (tmp_path / "proxy-events.jsonl").read_text(encoding="utf-8")
    for reason in (
        "undeclared-provider-path",
        "model-mismatch",
        "invalid-request-json",
        "proxy-authentication-failed",
        "route-control-forbidden",
    ):
        assert reason in evidence
    assert "attacker.invalid" not in evidence


def test_token_and_cost_thresholds_stop_after_one_overshooting_response(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    recording_provider.enqueue_json(
        {
            "choices": [],
            "model": _MODEL,
            "usage": {"cost_usd": "1.25", "total_tokens": 11},
        }
    )
    body = _request_body()

    with _proxy(recording_provider, tmp_path, tokens=10, cost="1.00") as proxy:
        assert _post(proxy, body)[0] == 200
        assert _post(proxy, body)[0] == 429
        snapshot = proxy.snapshot

    assert len(recording_provider.requests) == 1
    assert snapshot.request_count == 1
    assert snapshot.provider_tokens == 11
    assert snapshot.provider_cost_usd == "1.25"
    evidence = [
        json.loads(line)
        for line in (tmp_path / "proxy-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    response = evidence[0]
    assert response["budget_events"] == [
        "tokens-stop-after-response",
        "cost-stop-after-response",
    ]
    assert response["token_overshoot"] == 1
    assert response["cost_overshoot_usd"] == "0.25"
    assert evidence[1]["event"] == "request-rejected"


def test_sixty_fifth_request_is_denied_without_an_upstream_retry(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    provider_response = {
        "choices": [],
        "model": _MODEL,
        "usage": {"cost_usd": "0", "total_tokens": 0},
    }
    for _ in range(64):
        recording_provider.enqueue_json(provider_response)

    with _proxy(recording_provider, tmp_path) as proxy:
        for _ in range(64):
            assert _post(proxy, _request_body())[0] == 200
        status, payload = _post(proxy, _request_body())
        snapshot = proxy.snapshot

    assert status == 429
    assert json.loads(payload)["error"]["code"] == "request-limit-reached"
    assert len(recording_provider.requests) == 64
    assert snapshot.request_count == 64


def test_missing_provider_usage_invalidates_the_route_after_streaming_response(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    response = {"choices": [], "model": _MODEL}
    recording_provider.enqueue_json(response)

    with _proxy(recording_provider, tmp_path) as proxy:
        assert _post(proxy, _request_body())[0] == 200
        assert _post(proxy, _request_body())[0] == 429
        snapshot = proxy.snapshot

    assert snapshot.blocked_reason == "provider-contract-violation"
    assert len(recording_provider.requests) == 1
    evidence = (tmp_path / "proxy-events.jsonl").read_text(encoding="utf-8")
    assert '"reason_code":"provider-contract-violation"' in evidence


def test_provider_failed_native_retry_is_observed_and_charged_without_proxy_retry(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    charged_failure = {
        "error": {"message": "temporary"},
        "model": _MODEL,
        "usage": {"cost_usd": "0.20", "total_tokens": 7},
    }
    success = {
        "choices": [],
        "model": _MODEL,
        "usage": {"cost_usd": "0.30", "total_tokens": 9},
    }
    recording_provider.enqueue_json(charged_failure, status=503)
    recording_provider.enqueue_json(success)

    with _proxy(recording_provider, tmp_path) as proxy:
        assert _post(proxy, _request_body())[0] == 503
        assert _post(proxy, _request_body())[0] == 200
        snapshot = proxy.snapshot

    assert len(recording_provider.requests) == 2
    assert snapshot.request_count == 2
    assert snapshot.provider_tokens == 16
    assert snapshot.provider_cost_usd == "0.50"
