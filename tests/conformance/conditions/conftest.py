from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@dataclass
class ProviderScript:
    """Scripted loopback provider for launch-module conformance runs."""

    responses: list[tuple[int, bytes]] = field(default_factory=list)
    requests: list[dict[str, object]] = field(default_factory=list)

    def enqueue_envelope(self, *, path: str, content: str) -> None:
        message = {
            "content": json.dumps({"content": content, "path": path}),
            "refusal": None,
            "role": "assistant",
        }
        body = json.dumps(
            {
                "choices": [{"finish_reason": "stop", "index": 0, "message": message}],
                "usage": {"cost_usd": "0.10", "total_tokens": 23},
            }
        ).encode("utf-8")
        self.responses.append((200, body))

    def enqueue_failure(self, status: int) -> None:
        self.responses.append((status, b"{}"))


@pytest.fixture
def provider() -> Iterator[tuple[str, ProviderScript]]:
    script = ProviderScript()

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server contract
            length = int(self.headers.get("Content-Length", "0"))
            script.requests.append(
                {
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(length)),
                    "path": self.path,
                }
            )
            status, body = script.responses.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *arguments: object) -> None:
            del arguments

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", script
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
