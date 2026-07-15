from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Iterator
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


@dataclass(frozen=True)
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: bytes


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self.responses: deque[ProviderResponse] = deque()
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
                            headers={name.lower(): value for name, value in self.headers.items()},
                            body=body,
                        )
                    )
                    response = fixture.responses.popleft()
                self.send_response(response.status)
                self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(response.body)))
                if response.cost_header is not None:
                    self.send_header("X-Provider-Cost-Usd", response.cost_header)
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
        return f"http://{host}:{port}/v1"

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
def recording_provider() -> Iterator[RecordingProvider]:
    with RecordingProvider() as provider:
        yield provider
