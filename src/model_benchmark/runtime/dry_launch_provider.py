from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit


DRY_LAUNCH_ENV = "MODEL_BENCHMARK_DRY_LAUNCH"
DRY_LAUNCH_API_KEY = "functional-v1-dry-launch-local-provider"
DRY_LAUNCH_RESPONSE = (
    "Dry-launch lifecycle qualification only. Finish now without modifying files."
)


class DryLaunchProviderError(ValueError):
    """The deterministic local provider could not be configured safely."""


class DryLaunchProvider:
    """Loopback-only OpenAI-compatible responder for no-spend qualification."""

    def __init__(self, *, model: str, route_prefix: str) -> None:
        if not model or any(ord(character) < 32 for character in model):
            raise DryLaunchProviderError("model must be non-empty control-free text")
        if route_prefix in {"", "/"}:
            route_prefix = ""
        elif not route_prefix.startswith("/") or route_prefix.endswith("/"):
            raise DryLaunchProviderError(
                "route prefix must be absolute without a trailing slash"
            )
        self.model = model
        self.route_prefix = route_prefix
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise DryLaunchProviderError("local provider has not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{self.route_prefix}"

    def __enter__(self) -> Self:
        if self._server is not None:
            raise DryLaunchProviderError("local provider is already running")
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_arguments: object) -> None:
                return

            def do_POST(self) -> None:
                expected_path = provider.route_prefix + "/chat/completions"
                if urlsplit(self.path).path != expected_path:
                    self._error(404, "undeclared-provider-path")
                    return
                if self.headers.get("Authorization") != f"Bearer {DRY_LAUNCH_API_KEY}":
                    self._error(401, "provider-authentication-failed")
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                    request = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeError, ValueError, json.JSONDecodeError):
                    self._error(400, "invalid-request-json")
                    return
                if (
                    not isinstance(request, dict)
                    or request.get("model") != provider.model
                ):
                    self._error(400, "model-mismatch")
                    return
                if request.get("stream") is True:
                    content_type = "text/event-stream"
                    body = _stream_response(provider.model)
                else:
                    content_type = "application/json"
                    body = _json_response(provider.model)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status: int, code: str) -> None:
                body = json.dumps(
                    {
                        "error": {
                            "code": code,
                            "message": code,
                            "type": "invalid_request_error",
                        }
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="functional-v1-dry-launch-provider",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)


def _usage() -> dict[str, int]:
    return {"completion_tokens": 1, "prompt_tokens": 1, "total_tokens": 2}


def _json_response(model: str) -> bytes:
    value = {
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {"content": DRY_LAUNCH_RESPONSE, "role": "assistant"},
            }
        ],
        "created": 0,
        "id": "functional-v1-dry-launch",
        "model": model,
        "object": "chat.completion",
        "usage": _usage(),
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _stream_response(model: str) -> bytes:
    first = {
        "choices": [
            {
                "delta": {"content": DRY_LAUNCH_RESPONSE, "role": "assistant"},
                "finish_reason": None,
                "index": 0,
            }
        ],
        "created": 0,
        "id": "functional-v1-dry-launch",
        "model": model,
        "object": "chat.completion.chunk",
    }
    final = {
        "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
        "created": 0,
        "id": "functional-v1-dry-launch",
        "model": model,
        "object": "chat.completion.chunk",
        "usage": _usage(),
    }
    events = [
        "data: " + json.dumps(first, sort_keys=True, separators=(",", ":")),
        "data: " + json.dumps(final, sort_keys=True, separators=(",", ":")),
        "data: [DONE]",
    ]
    return ("\n\n".join(events) + "\n\n").encode("utf-8")
