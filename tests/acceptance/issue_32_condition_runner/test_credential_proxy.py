from __future__ import annotations

import http.client
import json
import signal
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

import model_benchmark.runtime.credential_proxy_service as proxy_service
from model_benchmark.runtime.credential_proxy import (
    CredentialProxy,
    CredentialProxyConfig,
    CredentialProxyError,
    PricingRecord,
    _usage_token_counts,
)
from model_benchmark.runtime.dry_launch_provider import (
    DRY_LAUNCH_API_KEY,
    DRY_LAUNCH_ENV,
    DRY_LAUNCH_RESPONSE,
    DryLaunchProvider,
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
    pricing: PricingRecord | None = None,
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
            pricing_record=pricing,
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
    assert all(
        request.path == "/v1/chat/completions"
        for request in recording_provider.requests
    )
    assert all(
        request.headers["authorization"] == f"Bearer {_REAL_KEY}"
        for request in recording_provider.requests
    )
    evidence = (tmp_path / "proxy-events.jsonl").read_bytes()
    assert evidence.count(b'"event":"provider-response"') == 2
    assert _REAL_KEY.encode() not in evidence
    assert _TRIAL_TOKEN.encode() not in evidence
    assert b"private prompt bytes" not in evidence


def test_ua_less_client_requests_gain_the_proxy_user_agent(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    # Cloudflare tarpits UA-less upstream requests (issue #99): the proxy
    # must fill an honest User-Agent for stdlib clients that send none.
    recording_provider.enqueue_json({"choices": [], "model": _MODEL})

    with _proxy(recording_provider, tmp_path) as proxy:
        assert _post(proxy, _request_body())[0] == 200

    (request,) = recording_provider.requests
    assert request.headers["user-agent"] == "model-benchmark-credential-proxy/1"


def test_client_user_agents_pass_through_unmodified(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    recording_provider.enqueue_json({"choices": [], "model": _MODEL})

    with _proxy(recording_provider, tmp_path) as proxy:
        status, _ = _post(
            proxy,
            _request_body(),
            headers={"User-Agent": "harness-client/7"},
        )

    assert status == 200
    (request,) = recording_provider.requests
    assert request.headers["user-agent"] == "harness-client/7"


def test_route_model_and_auth_controls_fail_closed_before_provider(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    with _proxy(recording_provider, tmp_path) as proxy:
        assert _post(proxy, _request_body(), path="/responses")[0] == 404
        assert _post(proxy, _request_body(model="wrong/model"))[0] == 400
        assert _post(proxy, b'{"model":"locked/model","model":"wrong/model"}')[0] == 400
        assert _post(proxy, _request_body(), token="wrong-token")[0] == 401
        assert (
            _post(
                proxy,
                _request_body(),
                headers={"X-Upstream-Url": "https://attacker.invalid/v1"},
            )[0]
            == 400
        )

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
        for line in (tmp_path / "proxy-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    response = evidence[0]
    assert response["budget_events"] == [
        "tokens-stop-after-response",
        "cost-stop-after-response",
    ]
    assert response["token_overshoot"] == 1
    assert response["cost_overshoot_usd"] == "0.25"
    assert evidence[1]["event"] == "request-rejected"


def test_pricing_record_derives_cost_when_provider_omits_cost(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    pricing = PricingRecord(
        identity="pricing-record:sha256:" + "0" * 64,
        input_usd_per_million_tokens=Decimal("0.10"),
        output_usd_per_million_tokens=Decimal("0.20"),
    )
    recording_provider.enqueue_json(
        {
            "choices": [],
            "model": _MODEL,
            "usage": {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 500_000,
                "total_tokens": 1_500_000,
            },
        }
    )

    with _proxy(
        recording_provider,
        tmp_path,
        tokens=2_000_000,
        cost="0.15",
        pricing=pricing,
    ) as proxy:
        assert _post(proxy, _request_body())[0] == 200
        assert _post(proxy, _request_body())[0] == 429
        snapshot = proxy.snapshot

    assert snapshot.provider_cost_usd == "0.20"
    event = json.loads(
        (tmp_path / "proxy-events.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert event["provider_reported_cost_usd"] is None
    assert event["provider_cost_usd"] == "0.20"
    assert event["cost_components_usd"] == {
        "input": "0.10",
        "output": "0.10",
    }
    assert event["pricing_record_identity"] == pricing.identity
    assert event["budget_events"] == ["cost-stop-after-response"]


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


def test_stream_cost_event_records_maximum_reported_cost_despite_trailing_zero(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    stream = (
        b'data: {"choices":[{"delta":{"content":"ok"}}],"model":"locked/model"}\n\n'
        b'data: {"choices":[],"model":"locked/model","usage":{"total_tokens":98}}\n\n'
        b'data: {"choices":[],"x-opencode-type":"inference-cost","cost":"0.00001484",'
        b'"normalizedUsage":{"inputTokens":90,"outputTokens":8}}\n\n'
        b"data: [DONE]\n\n"
        b'data: {"choices":[],"cost":"0"}\n\n'
    )
    recording_provider.enqueue_bytes(
        stream,
        content_type="text/event-stream",
        chunks=(9, 17, 3, 28),
    )

    with _proxy(recording_provider, tmp_path) as proxy:
        status, payload = _post(proxy, _request_body())
        snapshot = proxy.snapshot

    assert (status, payload) == (200, stream)
    assert snapshot.blocked_reason is None
    assert snapshot.provider_tokens == 98
    assert snapshot.provider_cost_usd == "0.00001484"


def test_top_level_cost_string_zero_is_valid_reported_spend(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    provider_response = {
        "choices": [],
        "cost": "0",
        "model": _MODEL,
        "usage": {"total_tokens": 98},
    }
    recording_provider.enqueue_json(provider_response)
    recording_provider.enqueue_json(provider_response)

    with _proxy(recording_provider, tmp_path) as proxy:
        assert _post(proxy, _request_body())[0] == 200
        assert _post(proxy, _request_body())[0] == 200
        snapshot = proxy.snapshot

    assert snapshot.blocked_reason is None
    assert snapshot.request_count == 2
    assert snapshot.provider_tokens == 196
    assert snapshot.provider_cost_usd == "0"


def test_zero_request_trial_still_produces_readable_empty_evidence(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "proxy-events.jsonl"
    with _proxy(recording_provider, tmp_path):
        assert evidence_path.is_file()
    assert evidence_path.read_bytes() == b""
    assert recording_provider.requests == []


def test_missing_token_split_under_pricing_record_blocks_fail_closed(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    # With a pricing record sealed, a successful response that reports no
    # input/output token split cannot be priced; a reported cost figure alone
    # must not satisfy the contract, or budget enforcement silently degrades.
    pricing = PricingRecord(
        identity="pricing-record:sha256:" + "0" * 64,
        input_usd_per_million_tokens=Decimal("0.10"),
        output_usd_per_million_tokens=Decimal("0.20"),
    )
    recording_provider.enqueue_json(
        {
            "choices": [],
            "cost": "0.05",
            "model": _MODEL,
            "usage": {"total_tokens": 128},
        }
    )

    with _proxy(recording_provider, tmp_path, pricing=pricing) as proxy:
        assert _post(proxy, _request_body())[0] == 200
        assert _post(proxy, _request_body())[0] == 429
        snapshot = proxy.snapshot

    assert snapshot.blocked_reason == "provider-contract-violation"
    assert len(recording_provider.requests) == 1
    assert snapshot.provider_tokens == 0
    assert snapshot.provider_cost_usd == "0"
    event = json.loads(
        (tmp_path / "proxy-events.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert event["reason_code"] == "provider-contract-violation"
    assert event["provider_cost_usd"] is None
    assert event["provider_reported_cost_usd"] == "0.05"


def test_enforcement_uses_derived_total_and_records_reported_cost_alongside(
    recording_provider: Any,
    tmp_path: Path,
) -> None:
    # Dual accounting: stop-after-cost is enforced against the total derived
    # at the sealed rates (0.20 crosses the 0.15 stop) while the
    # provider-reported figure (0.05, which alone would not stop the Trial)
    # is recorded alongside.
    pricing = PricingRecord(
        identity="pricing-record:sha256:" + "0" * 64,
        input_usd_per_million_tokens=Decimal("0.10"),
        output_usd_per_million_tokens=Decimal("0.20"),
    )
    recording_provider.enqueue_json(
        {
            "choices": [],
            "cost": "0.05",
            "model": _MODEL,
            "usage": {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 500_000,
                "total_tokens": 1_500_000,
            },
        }
    )

    with _proxy(
        recording_provider,
        tmp_path,
        tokens=2_000_000,
        cost="0.15",
        pricing=pricing,
    ) as proxy:
        assert _post(proxy, _request_body())[0] == 200
        assert _post(proxy, _request_body())[0] == 429
        snapshot = proxy.snapshot

    assert snapshot.blocked_reason == "cost-stop-after-response"
    assert snapshot.provider_cost_usd == "0.20"
    event = json.loads(
        (tmp_path / "proxy-events.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert event["provider_cost_usd"] == "0.20"
    assert event["provider_reported_cost_usd"] == "0.05"
    assert event["cost_components_usd"] == {"input": "0.10", "output": "0.10"}
    assert event["pricing_record_identity"] == pricing.identity
    assert event["budget_events"] == ["cost-stop-after-response"]


@pytest.mark.parametrize(
    ("identity", "input_rate", "output_rate", "message"),
    [
        ("not-a-typed-digest", "0.10", "0.20", "identity is invalid"),
        ("artifact:sha256:" + "0" * 64, "0.10", "0.20", "wrong kind"),
        ("pricing-record:sha256:" + "0" * 64, "0", "0.20", "finite and positive"),
        ("pricing-record:sha256:" + "0" * 64, "0.10", "-0.20", "finite and positive"),
        ("pricing-record:sha256:" + "0" * 64, "NaN", "0.20", "finite and positive"),
        (
            "pricing-record:sha256:" + "0" * 64,
            "0.10",
            "Infinity",
            "finite and positive",
        ),
    ],
)
def test_pricing_record_rejects_invalid_identity_and_rates(
    identity: str,
    input_rate: str,
    output_rate: str,
    message: str,
) -> None:
    with pytest.raises(CredentialProxyError, match=message):
        PricingRecord(
            identity=identity,
            input_usd_per_million_tokens=Decimal(input_rate),
            output_usd_per_million_tokens=Decimal(output_rate),
        )


def test_usage_token_counts_accept_alternate_field_names() -> None:
    assert _usage_token_counts(
        {"total_tokens": 12, "input_tokens": 5, "output_tokens": 7}
    ) == (12, 5, 7)
    assert _usage_token_counts(
        {"total_tokens": 12, "prompt_tokens": 5, "completion_tokens": 7}
    ) == (12, 5, 7)
    # The OpenAI-compatible names win over the fallbacks when both appear.
    assert _usage_token_counts(
        {
            "completion_tokens": 7,
            "input_tokens": 9,
            "output_tokens": 9,
            "prompt_tokens": 5,
            "total_tokens": 12,
        }
    ) == (12, 5, 7)
    # Booleans and negatives are not token counts.
    assert _usage_token_counts(
        {"total_tokens": True, "prompt_tokens": -1, "completion_tokens": 7}
    ) == (None, None, 7)


_SERVICE_ENVIRONMENT = {
    "MODEL_BENCHMARK_PROVIDER_BASE_URL": "https://provider.example/v1",
    "MODEL_BENCHMARK_PROVIDER_MODEL": _MODEL,
    "MODEL_BENCHMARK_REQUESTS_PER_TRIAL": "64",
    "MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL": "100000",
    "MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL": "5.00",
    "MODEL_BENCHMARK_PRICING_RECORD_IDENTITY": "pricing-record:sha256:" + "0" * 64,
    "MODEL_BENCHMARK_INPUT_USD_PER_MILLION_TOKENS": "0.14",
    "MODEL_BENCHMARK_OUTPUT_USD_PER_MILLION_TOKENS": "0.28",
    "MODEL_BENCHMARK_PROVIDER_API_KEY": _REAL_KEY,
    "MODEL_BENCHMARK_PROXY_TOKEN": _TRIAL_TOKEN,
}


def _preserving_signal_handlers() -> list[tuple[int, object]]:
    return [
        (selected, signal.getsignal(selected))
        for selected in (signal.SIGINT, signal.SIGTERM)
    ]


def test_service_main_builds_its_config_from_the_cell_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _SERVICE_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    captured: dict[str, CredentialProxyConfig] = {}

    class _ImmediateStopProxy:
        def __init__(self, config: CredentialProxyConfig) -> None:
            captured["config"] = config

        def __enter__(self) -> _ImmediateStopProxy:
            signal.raise_signal(signal.SIGTERM)
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(proxy_service, "CredentialProxy", _ImmediateStopProxy)
    saved = _preserving_signal_handlers()
    try:
        assert proxy_service.main() == 0
    finally:
        for selected, handler in saved:
            signal.signal(selected, handler)

    config = captured["config"]
    assert config.upstream_base_url == "https://provider.example/v1"
    assert config.model == _MODEL
    assert config.requests_per_trial == 64
    assert config.provider_tokens_per_trial == 100_000
    assert config.stop_after_cost_usd_per_trial == Decimal("5.00")
    assert config.evidence_path == Path("/evidence/proxy.jsonl")
    assert config.listen_host == "0.0.0.0"
    assert config.listen_port == 8080
    assert config.real_api_key == _REAL_KEY
    assert config.trial_token == _TRIAL_TOKEN
    pricing = config.pricing_record
    assert pricing is not None
    assert pricing.identity == "pricing-record:sha256:" + "0" * 64
    assert pricing.input_usd_per_million_tokens == Decimal("0.14")
    assert pricing.output_usd_per_million_tokens == Decimal("0.28")


def test_service_main_fails_at_startup_when_an_environment_variable_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _SERVICE_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MODEL_BENCHMARK_REQUESTS_PER_TRIAL")

    class _UnreachableProxy:
        def __init__(self, config: CredentialProxyConfig) -> None:
            raise AssertionError("the proxy must not start without its request cap")

    monkeypatch.setattr(proxy_service, "CredentialProxy", _UnreachableProxy)
    saved = _preserving_signal_handlers()
    try:
        with pytest.raises(KeyError, match="MODEL_BENCHMARK_REQUESTS_PER_TRIAL"):
            proxy_service.main()
    finally:
        for selected, handler in saved:
            signal.signal(selected, handler)


def test_dry_launch_provider_is_loopback_only_and_openai_compatible() -> None:
    with DryLaunchProvider(model=_MODEL, route_prefix="/v1") as provider:
        parsed = urlsplit(provider.base_url)
        assert parsed.hostname == "127.0.0.1"
        assert parsed.path == "/v1"
        for streaming in (False, True):
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=5
            )
            body = json.dumps({"model": _MODEL, "stream": streaming})
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={
                    "Authorization": f"Bearer {DRY_LAUNCH_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            payload = response.read()
            connection.close()
            assert response.status == 200
            assert DRY_LAUNCH_RESPONSE.encode() in payload
            assert b'"total_tokens":2' in payload
            assert (b"data: [DONE]" in payload) is streaming


def test_service_dry_launch_uses_no_real_provider_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _SERVICE_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(DRY_LAUNCH_ENV, "1")
    captured: dict[str, str] = {}

    class _LocalProvider:
        base_url = "http://127.0.0.1:12345/v1"

        def __init__(self, *, model: str, route_prefix: str) -> None:
            assert model == _MODEL
            assert route_prefix == "/v1"

        def __enter__(self) -> _LocalProvider:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def serve(_stop: object, *, upstream_base_url: str, real_api_key: str) -> int:
        captured["upstream"] = upstream_base_url
        captured["key"] = real_api_key
        return 0

    monkeypatch.setattr(proxy_service, "DryLaunchProvider", _LocalProvider)
    monkeypatch.setattr(proxy_service, "_serve", serve)
    saved = _preserving_signal_handlers()
    try:
        assert proxy_service.main() == 0
    finally:
        for selected, handler in saved:
            signal.signal(selected, handler)

    assert captured == {
        "key": DRY_LAUNCH_API_KEY,
        "upstream": "http://127.0.0.1:12345/v1",
    }
