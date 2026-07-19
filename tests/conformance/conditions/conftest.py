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
        # The launch module streams its one request (issue #99): replay the
        # OpenAI-compatible SSE shape and let it assemble the deltas.
        payload = json.dumps({"content": content, "path": path})
        events: list[dict[str, object]] = [
            {"choices": [{"delta": {"role": "assistant"}, "index": 0}]}
        ]
        events.extend(
            {"choices": [{"delta": {"content": payload[start : start + 7]}, "index": 0}]}
            for start in range(0, len(payload), 7)
        )
        events.append({"choices": [], "usage": {"cost_usd": "0.10", "total_tokens": 23}})
        body = b"".join(
            b"data: " + json.dumps(event).encode("utf-8") + b"\n\n" for event in events
        ) + b"data: [DONE]\n\n"
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
