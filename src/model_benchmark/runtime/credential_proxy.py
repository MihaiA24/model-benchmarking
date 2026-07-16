from __future__ import annotations

import http.client
import json
import os
import secrets
import ssl
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self
from urllib.parse import SplitResult, urlsplit

from model_benchmark.declarations.canonical import canonical_json_bytes


PROVIDER_API_KEY_ENV = "MODEL_BENCHMARK_PROVIDER_API_KEY"
TRIAL_PROXY_TOKEN_ENV = "MODEL_BENCHMARK_PROXY_TOKEN"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_ROUTE_CONTROL_HEADERS = frozenset(
    {
        "x-api-base",
        "x-base-url",
        "x-model",
        "x-provider-route",
        "x-target-url",
        "x-upstream-url",
    }
)
_ROUTE_CONTROL_FIELDS = frozenset(
    {"api_base", "base_url", "endpoint", "path", "provider", "route", "url"}
)


class CredentialProxyError(ValueError):
    """A per-Trial proxy could not be configured safely."""


@dataclass(frozen=True)
class CredentialProxyConfig:
    upstream_base_url: str
    model: str
    provider_tokens_per_trial: int
    stop_after_cost_usd_per_trial: Decimal
    evidence_path: Path
    requests_per_trial: int = 64
    listen_host: str = "127.0.0.1"
    listen_port: int = 0
    allowed_endpoint_paths: tuple[str, ...] = ("/chat/completions",)
    real_api_key: str = field(repr=False, default="")
    trial_token: str = field(repr=False, default="")

    def __post_init__(self) -> None:
        parsed = urlsplit(self.upstream_base_url)
        loopback_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "::1",
            "localhost",
        }
        if (
            (parsed.scheme != "https" and not loopback_http)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.hostname is None
        ):
            raise CredentialProxyError(
                "upstream base URL must be HTTPS, or loopback HTTP for qualification"
            )
        if parsed.path not in {"", "/"} and parsed.path.endswith("/"):
            raise CredentialProxyError("upstream base URL must not end with a slash")
        if not self.model or any(ord(character) < 32 for character in self.model):
            raise CredentialProxyError("model must be non-empty control-free text")
        if self.listen_host not in {"127.0.0.1", "0.0.0.0"}:
            raise CredentialProxyError(
                "proxy listen host must be loopback or all IPv4 interfaces"
            )
        if (
            not isinstance(self.listen_port, int)
            or isinstance(self.listen_port, bool)
            or not 0 <= self.listen_port <= 65535
        ):
            raise CredentialProxyError("proxy listen port must be between 0 and 65535")
        if (
            not isinstance(self.requests_per_trial, int)
            or isinstance(self.requests_per_trial, bool)
            or self.requests_per_trial <= 0
        ):
            raise CredentialProxyError("provider request limit must be positive")
        if self.provider_tokens_per_trial <= 0:
            raise CredentialProxyError("provider token threshold must be positive")
        if (
            not self.stop_after_cost_usd_per_trial.is_finite()
            or self.stop_after_cost_usd_per_trial <= 0
        ):
            raise CredentialProxyError("provider cost threshold must be positive")
        if not self.real_api_key or not self.trial_token:
            raise CredentialProxyError("proxy credentials must be non-empty")
        if any(
            character in value
            for value in (self.real_api_key, self.trial_token)
            for character in "\r\n\x00"
        ):
            raise CredentialProxyError("proxy credentials must be header-safe")
        if self.real_api_key == self.trial_token:
            raise CredentialProxyError(
                "proxy token must differ from the provider credential"
            )
        if not self.allowed_endpoint_paths:
            raise CredentialProxyError(
                "at least one provider endpoint path is required"
            )
        for value in self.allowed_endpoint_paths:
            path = PurePosixPath(value)
            if (
                not value.startswith("/")
                or value == "/"
                or ".." in path.parts
                or "//" in value
                or "?" in value
                or "#" in value
                or path.as_posix() != value
            ):
                raise CredentialProxyError(f"invalid provider endpoint path: {value!r}")
        if len(set(self.allowed_endpoint_paths)) != len(self.allowed_endpoint_paths):
            raise CredentialProxyError("provider endpoint paths must be unique")

    @classmethod
    def create(
        cls,
        *,
        upstream_base_url: str,
        model: str,
        real_api_key: str,
        provider_tokens_per_trial: int,
        stop_after_cost_usd_per_trial: Decimal,
        evidence_path: Path,
        requests_per_trial: int = 64,
        allowed_endpoint_paths: tuple[str, ...] = ("/chat/completions",),
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
    ) -> Self:
        return cls(
            upstream_base_url=upstream_base_url,
            model=model,
            real_api_key=real_api_key,
            trial_token=secrets.token_urlsafe(32),
            provider_tokens_per_trial=provider_tokens_per_trial,
            stop_after_cost_usd_per_trial=stop_after_cost_usd_per_trial,
            evidence_path=evidence_path,
            requests_per_trial=requests_per_trial,
            listen_host=listen_host,
            listen_port=listen_port,
            allowed_endpoint_paths=allowed_endpoint_paths,
        )


@dataclass(frozen=True)
class ProxySnapshot:
    request_count: int
    provider_tokens: int
    provider_cost_usd: str
    blocked_reason: str | None


class _MetadataObserver:
    def __init__(self, content_type: str) -> None:
        self._is_event_stream = (
            content_type.split(";", 1)[0].strip().lower() == "text/event-stream"
        )
        self._buffer = bytearray()
        self._too_large = False
        self.model: str | None = None
        self.tokens: int | None = None
        self.cost: Decimal | None = None

    def feed(self, chunk: bytes) -> None:
        if self._too_large:
            return
        self._buffer.extend(chunk)
        if len(self._buffer) > MAX_METADATA_BYTES:
            self._buffer.clear()
            self._too_large = True
            return
        if not self._is_event_stream:
            return
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                return
            line = bytes(self._buffer[:newline]).rstrip(b"\r")
            del self._buffer[: newline + 1]
            if line.startswith(b"data:"):
                payload = line[5:].lstrip()
                if payload and payload != b"[DONE]":
                    self._observe_json(payload)

    def finish(self) -> None:
        if self._too_large:
            return
        if self._is_event_stream:
            if self._buffer.startswith(b"data:"):
                payload = bytes(self._buffer[5:]).strip()
                if payload and payload != b"[DONE]":
                    self._observe_json(payload)
            self._buffer.clear()
            return
        self._observe_json(bytes(self._buffer))
        self._buffer.clear()

    def _observe_json(self, payload: bytes) -> None:
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(value, dict):
            return
        model = value.get("model")
        if isinstance(model, str):
            self.model = model
        usage = value.get("usage")
        if isinstance(usage, dict):
            tokens = usage.get("total_tokens")
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                self.tokens = tokens
            self._observe_cost(usage)
        self._observe_cost(value)

    def _observe_cost(self, value: dict[str, object]) -> None:
        # Providers report spend as `cost_usd` or `cost` (opencode zen); one
        # response may carry several cost events (zen appends a zero-cost
        # event after [DONE]), so keep the per-response maximum.
        for field in ("cost_usd", "cost"):
            parsed = _parse_cost(value.get(field))
            if parsed is not None and (self.cost is None or parsed > self.cost):
                self.cost = parsed


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = child
    return value


def _parse_cost(value: object) -> Decimal | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _canonical_cost(value: Decimal) -> str:
    return format(value, "f")


class _ProxyState:
    def __init__(self, config: CredentialProxyConfig) -> None:
        self.config = config
        self.gate = threading.Lock()
        self.evidence_lock = threading.Lock()
        self.request_count = 0
        self.provider_tokens = 0
        self.provider_cost = Decimal(0)
        self.blocked_reason: str | None = None

    def append_evidence(self, event: dict[str, object]) -> None:
        forbidden = (
            self.config.real_api_key.encode(),
            self.config.trial_token.encode(),
        )
        data = canonical_json_bytes(event) + b"\n"
        if any(secret in data for secret in forbidden):
            raise RuntimeError("proxy evidence contains a credential")
        path = self.config.evidence_path
        with self.evidence_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, data)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def snapshot(self) -> ProxySnapshot:
        with self.gate:
            return ProxySnapshot(
                request_count=self.request_count,
                provider_tokens=self.provider_tokens,
                provider_cost_usd=_canonical_cost(self.provider_cost),
                blocked_reason=self.blocked_reason,
            )


class CredentialProxy:
    """One host-side, one-Trial OpenAI-compatible credential boundary."""

    def __init__(self, config: CredentialProxyConfig) -> None:
        self.config = config
        self._state = _ProxyState(config)
        handler = self._handler_type()
        self._server = ThreadingHTTPServer(
            (config.listen_host, config.listen_port), handler
        )
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        parsed = urlsplit(self.config.upstream_base_url)
        prefix = "" if parsed.path in {"", "/"} else parsed.path
        host, port = self._server.server_address
        advertised_host = "127.0.0.1" if host == "0.0.0.0" else host
        return f"http://{advertised_host}:{port}{prefix}"

    @property
    def trial_environment(self) -> dict[str, str]:
        return {TRIAL_PROXY_TOKEN_ENV: self.config.trial_token}

    @property
    def snapshot(self) -> ProxySnapshot:
        return self._state.snapshot()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Credential Proxy is already started")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="model-benchmark-credential-proxy",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("Credential Proxy did not stop")
        self._thread = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        state = self._state

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_arguments: object) -> None:
                return

            def do_GET(self) -> None:
                self.close_connection = True
                if urlsplit(self.path).path != "/healthz":
                    self._send_error(404, "undeclared-proxy-path")
                    return
                body = canonical_json_bytes({"status": "ready"})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                self.close_connection = True
                with state.gate:
                    self._handle_locked()

            def _handle_locked(self) -> None:
                started_ns = time.monotonic_ns()
                rejection = self._validate_request()
                if rejection is not None:
                    reason, status = rejection
                    state.append_evidence(
                        {
                            "budget_events": [],
                            "duration_ns": time.monotonic_ns() - started_ns,
                            "event": "request-rejected",
                            "reason_code": reason,
                            "request_count": state.request_count,
                            "schema_version": 1,
                            "status": status,
                        }
                    )
                    self._send_error(status, reason)
                    return
                content_length = int(self.headers["Content-Length"])
                body = self.rfile.read(content_length)
                if len(body) != content_length:
                    self._reject_after_read(started_ns, "incomplete-request-body", 400)
                    return
                try:
                    request_value = json.loads(
                        body.decode("utf-8", errors="strict"),
                        object_pairs_hook=_unique_json_object,
                    )
                except (UnicodeError, json.JSONDecodeError, ValueError):
                    self._reject_after_read(started_ns, "invalid-request-json", 400)
                    return
                if not isinstance(request_value, dict):
                    self._reject_after_read(started_ns, "invalid-request-object", 400)
                    return
                if any(field in request_value for field in _ROUTE_CONTROL_FIELDS):
                    self._reject_after_read(started_ns, "route-control-forbidden", 400)
                    return
                model_field = (
                    "name"
                    if urlsplit(self.path).path.endswith("/api/show")
                    else "model"
                )
                if request_value.get(model_field) != state.config.model:
                    self._reject_after_read(started_ns, "model-mismatch", 400)
                    return

                state.request_count += 1
                request_index = state.request_count
                self._forward(body, request_index=request_index, started_ns=started_ns)

            def _validate_request(self) -> tuple[str, int] | None:
                parsed_target = urlsplit(self.path)
                if (
                    parsed_target.scheme
                    or parsed_target.netloc
                    or parsed_target.query
                    or parsed_target.fragment
                ):
                    return "undeclared-provider-route", 404
                upstream = urlsplit(state.config.upstream_base_url)
                prefix = "" if upstream.path in {"", "/"} else upstream.path
                allowed = {
                    f"{prefix}{path}" for path in state.config.allowed_endpoint_paths
                }
                if parsed_target.path not in allowed:
                    return "undeclared-provider-path", 404
                if any(name.lower() in _ROUTE_CONTROL_HEADERS for name in self.headers):
                    return "route-control-forbidden", 400
                if self.headers.get_all("Authorization", []) != [
                    f"Bearer {state.config.trial_token}"
                ]:
                    return "proxy-authentication-failed", 401
                if len(self.headers.get_all("Content-Length", [])) != 1:
                    return "invalid-request-length", 400
                if len(self.headers.get_all("Content-Type", [])) != 1:
                    return "invalid-request-content-type", 415
                if state.blocked_reason is not None:
                    return state.blocked_reason, 429
                if state.request_count >= state.config.requests_per_trial:
                    state.blocked_reason = "request-limit-reached"
                    return state.blocked_reason, 429
                if self.headers.get("Content-Encoding") not in {None, "identity"}:
                    return "encoded-request-forbidden", 400
                transfer_encoding = self.headers.get("Transfer-Encoding")
                if transfer_encoding is not None:
                    return "streamed-request-forbidden", 400
                raw_length = self.headers.get("Content-Length")
                try:
                    content_length = int(raw_length or "")
                except ValueError:
                    return "invalid-request-length", 400
                if content_length < 0 or content_length > MAX_REQUEST_BYTES:
                    return "request-size-limit", 413
                content_type = (
                    self.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type != "application/json":
                    return "invalid-request-content-type", 415
                return None

            def _reject_after_read(
                self, started_ns: int, reason: str, status: int
            ) -> None:
                state.append_evidence(
                    {
                        "budget_events": [],
                        "duration_ns": time.monotonic_ns() - started_ns,
                        "event": "request-rejected",
                        "reason_code": reason,
                        "request_count": state.request_count,
                        "schema_version": 1,
                        "status": status,
                    }
                )
                self._send_error(status, reason)

            def _forward(
                self, body: bytes, *, request_index: int, started_ns: int
            ) -> None:
                upstream = urlsplit(state.config.upstream_base_url)
                connection = _connection(upstream)
                headers = {
                    name: value
                    for name, value in self.headers.items()
                    if name.lower()
                    not in _HOP_BY_HOP_HEADERS
                    | {"authorization", "host", "content-length"}
                }
                headers["Authorization"] = f"Bearer {state.config.real_api_key}"
                headers["Content-Length"] = str(len(body))
                try:
                    connection.request("POST", self.path, body=body, headers=headers)
                    response = connection.getresponse()
                except (OSError, http.client.HTTPException, ssl.SSLError):
                    connection.close()
                    state.blocked_reason = "provider-connection-failed"
                    state.append_evidence(
                        {
                            "budget_events": [],
                            "duration_ns": time.monotonic_ns() - started_ns,
                            "event": "provider-failure",
                            "reason_code": state.blocked_reason,
                            "request_index": request_index,
                            "schema_version": 1,
                            "status": 502,
                        }
                    )
                    self._send_error(502, state.blocked_reason)
                    return

                content_type = response.getheader("Content-Type", "")
                header_cost = _parse_cost(response.getheader("X-Provider-Cost-Usd"))
                observer = _MetadataObserver(content_type)
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in _HOP_BY_HOP_HEADERS:
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                client_open = True
                try:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        observer.feed(chunk)
                        if client_open:
                            try:
                                self.wfile.write(chunk)
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                client_open = False
                finally:
                    response.close()
                    connection.close()
                observer.finish()
                if header_cost is not None:
                    observer.cost = header_cost
                self._record_response(
                    observer, response.status, request_index, started_ns
                )

            def _record_response(
                self,
                observer: _MetadataObserver,
                status: int,
                request_index: int,
                started_ns: int,
            ) -> None:
                successful = 200 <= status < 300
                reason_code: str | None = None
                budget_events: list[str] = []
                token_overshoot = 0
                cost_overshoot = Decimal(0)
                model_mismatch = (
                    observer.model is not None and observer.model != state.config.model
                )
                missing_success_metadata = successful and (
                    observer.model is None
                    or observer.tokens is None
                    or observer.cost is None
                )
                if model_mismatch or missing_success_metadata:
                    reason_code = "provider-contract-violation"
                    state.blocked_reason = reason_code
                elif observer.tokens is not None and observer.cost is not None:
                    state.provider_tokens += observer.tokens
                    state.provider_cost += observer.cost
                    token_overshoot = max(
                        0,
                        state.provider_tokens - state.config.provider_tokens_per_trial,
                    )
                    cost_overshoot = max(
                        Decimal(0),
                        state.provider_cost
                        - state.config.stop_after_cost_usd_per_trial,
                    )
                    if state.provider_tokens >= state.config.provider_tokens_per_trial:
                        budget_events.append("tokens-stop-after-response")
                    if (
                        state.provider_cost
                        >= state.config.stop_after_cost_usd_per_trial
                    ):
                        budget_events.append("cost-stop-after-response")
                    if budget_events:
                        state.blocked_reason = budget_events[0]
                event: dict[str, object] = {
                    "budget_events": budget_events,
                    "cost_overshoot_usd": _canonical_cost(cost_overshoot),
                    "duration_ns": time.monotonic_ns() - started_ns,
                    "event": "provider-response",
                    "provider_cost_usd": (
                        _canonical_cost(observer.cost)
                        if observer.cost is not None
                        else None
                    ),
                    "provider_model": observer.model,
                    "provider_tokens": observer.tokens,
                    "reason_code": reason_code,
                    "request_index": request_index,
                    "schema_version": 1,
                    "status": status,
                    "token_overshoot": token_overshoot,
                }
                state.append_evidence(event)

            def _send_error(self, status: int, reason_code: str) -> None:
                body = canonical_json_bytes(
                    {
                        "error": {
                            "code": reason_code,
                            "message": "Credential Proxy rejected the request",
                        }
                    }
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        return Handler


def _connection(parsed: SplitResult) -> http.client.HTTPConnection:
    port = parsed.port
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(
            parsed.hostname,
            port or 443,
            timeout=30,
            context=ssl.create_default_context(),
        )
    return http.client.HTTPConnection(parsed.hostname, port or 80, timeout=30)


def credential_fingerprint_forbidden(_credential: str) -> None:
    """Make reusable credential hashes an explicit unsupported operation."""

    raise CredentialProxyError(
        "provider credentials must never be fingerprinted or persisted"
    )
