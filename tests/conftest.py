"""Shared test doubles for every suite.

This file is part of every acceptance proof's sealed source closure
(see ``model_benchmark.evidence.pytest_acceptance``), so helpers here
stay inside each proof's inventory — unlike helper modules under
``tests/acceptance/``, which would sit outside the sealed digests.

``RecordingProvider`` is the single OpenAI-compatible provider double:
a response queue for exact-sequence suites (the issue-32 condition
runner and credential proxy) plus an optional default response for the
RPC-trial suites (issues 33/34/35), whose adapters make an unbounded
number of requests against a canned reply.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self

import pytest


@dataclass(frozen=True)
class ProviderResponse:
    status: int
    body: bytes
    content_type: str = "application/json"
    chunks: tuple[int, ...] = ()
    cost_header: str | None = None
    close_connection: bool = False


@dataclass(frozen=True)
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: bytes


class RecordingProvider:
    def __init__(
        self,
        *,
        base_path: str = "",
        default_response: ProviderResponse | None = None,
    ) -> None:
        self.requests: list[RecordedRequest] = []
        self.responses: deque[ProviderResponse] = deque()
        self._base_path = base_path
        self._default_response = default_response
        self._lock = threading.Lock()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_arguments: object) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                with fixture._lock:
                    fixture.requests.append(
                        RecordedRequest(
                            path=self.path,
                            headers={
                                name.lower(): value
                                for name, value in self.headers.items()
                            },
                            body=body,
                        )
                    )
                    if fixture.responses:
                        response = fixture.responses.popleft()
                    elif fixture._default_response is not None:
                        response = fixture._default_response
                    else:
                        response = fixture.responses.popleft()
                self.send_response(response.status)
                self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(response.body)))
                if response.cost_header is not None:
                    self.send_header("X-Provider-Cost-Usd", response.cost_header)
                if response.close_connection:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                if not response.chunks:
                    self.wfile.write(response.body)
                    self.wfile.flush()
                    return
                offset = 0
                for size in response.chunks:
                    self.wfile.write(response.body[offset : offset + size])
                    self.wfile.flush()
                    offset += size
                self.wfile.write(response.body[offset:])
                self.wfile.flush()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}{self._base_path}"

    def enqueue_json(
        self,
        value: object,
        *,
        status: int = 200,
        cost_header: str | None = None,
    ) -> None:
        self.responses.append(
            ProviderResponse(
                status=status,
                body=json.dumps(value, separators=(",", ":")).encode(),
                cost_header=cost_header,
            )
        )

    def enqueue(self, response: ProviderResponse) -> None:
        self.responses.append(response)

    def enqueue_bytes(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
        chunks: tuple[int, ...] = (),
        cost_header: str | None = None,
    ) -> None:
        self.enqueue(
            ProviderResponse(
                status=status,
                body=body,
                content_type=content_type,
                chunks=chunks,
                cost_header=cost_header,
            )
        )

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        assert not self._thread.is_alive()


@pytest.fixture
def recording_provider_factory() -> Callable[..., RecordingProvider]:
    def factory(
        *,
        base_path: str = "",
        default_json: object | None = None,
        default_cost_header: str | None = None,
    ) -> RecordingProvider:
        default_response = None
        if default_json is not None:
            default_response = ProviderResponse(
                status=200,
                body=json.dumps(default_json, separators=(",", ":")).encode(),
                cost_header=default_cost_header,
                close_connection=True,
            )
        return RecordingProvider(
            base_path=base_path, default_response=default_response
        )

    return factory
