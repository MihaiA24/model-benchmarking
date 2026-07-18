from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self

import pytest


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_arguments: object) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                body = self.rfile.read(length)
                owner.requests.append(
                    {
                        "authorization": self.headers.get("Authorization"),
                        "body": body,
                        "path": self.path,
                    }
                )
                payload = json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "index": 0,
                                "message": {"content": "done", "role": "assistant"},
                            }
                        ],
                        "model": "locked/model",
                        "usage": {
                            "completion_tokens": 5,
                            "cost_usd": "0.10",
                            "prompt_tokens": 12,
                            "total_tokens": 17,
                        },
                    },
                    separators=(",", ":"),
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Provider-Cost-Usd", "0.10")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

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


@pytest.fixture
def recording_provider() -> Iterator[RecordingProvider]:
    with RecordingProvider() as provider:
        yield provider
