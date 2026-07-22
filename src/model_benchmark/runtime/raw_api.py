from __future__ import annotations

import http.client
import json
import os
import stat
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

# This module is imported inside the sealed condition image, where only the
# standard library and the copied model_benchmark tree exist. Anything with a
# third-party closure (e.g. scenario_locks -> yaml) belongs in
# raw_api_locks.py; tests/architecture pins this boundary.
from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.runtime.conditions import FinalRepositoryHandoff


_MAX_PROVIDER_ENVELOPE_OVERHEAD = 1024 * 1024
# Worst-case ratio of SSE stream bytes to the content characters they carry
# (each delta chunk wraps a few characters in ~200 bytes of JSON framing).
_MAX_STREAM_EXPANSION = 64


class RawApiError(ValueError):
    """A rejected Raw API declaration, provider envelope, or materialization."""

    def __init__(
        self,
        reason_code: str,
        *,
        diagnostic_code: str | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.diagnostic_code = diagnostic_code


# The sealed Credential Proxy is reachable on loopback (conformance fixtures,
# sealed-process qualification) or as the pinned compose service name that
# execution.py wires into every live cell's MODEL_BENCHMARK_PROXY_BASE_URL.
# Issue #99: live cells use the in-mesh route; loopback-only rejection made
# every Raw API cell exit 78 before its one provider request.
_ALLOWED_PROXY_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "credential-proxy"})


@dataclass(frozen=True)
class RawApiRequest:
    proxy_base_url: str
    proxy_token: str
    model: str
    developer_brief: bytes
    repository: Path
    target_path: str
    max_content_bytes: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.proxy_base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in _ALLOWED_PROXY_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise RawApiError("Raw API must use the sealed Credential Proxy route")
        if not self.proxy_token or not self.model:
            raise RawApiError("Raw API proxy token and model must be non-empty")
        try:
            brief = self.developer_brief.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise RawApiError("Developer Brief must be strict UTF-8") from error
        if brief.startswith("\ufeff"):
            raise RawApiError("Developer Brief must not contain a UTF-8 BOM")
        _safe_target(self.target_path)
        if self.max_content_bytes <= 0:
            raise RawApiError("Raw API content limit must be positive")
        if not self.repository.is_dir() or self.repository.is_symlink():
            raise RawApiError("Raw API repository must be a real directory")


@dataclass(frozen=True)
class RawApiResult:
    outcome: str
    reason_code: str
    request_count: int
    provider_status: int | None
    materialized_path: str | None
    final_repository: FinalRepositoryHandoff | None
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in {"ready-for-capture", "valid_harness_outcome"}:
            raise ValueError("Raw API result outcome is invalid")
        if self.request_count != 1:
            raise ValueError("Raw API must make exactly one request")


class RawApiMaterializer:
    """One-request non-Harness condition that writes one locked UTF-8 file."""

    def materialize(self, request: RawApiRequest) -> RawApiResult:
        before = _snapshot(request.repository)
        status, response_body = _request_completion(request)
        if not 200 <= status < 300:
            return _failure("provider-failure", status)
        try:
            replacement = _decode_provider_response(response_body)
        except RawApiError as error:
            return _failure(
                error.reason_code,
                status,
                diagnostic_code=error.diagnostic_code,
            )
        except (UnicodeError, json.JSONDecodeError):
            return _failure("invalid-provider-json", status)
        if replacement["path"] != request.target_path:
            return _failure("response-path-mismatch", status)
        content = replacement["content"]
        assert isinstance(content, str)
        try:
            content_bytes = content.encode("utf-8", errors="strict")
        except UnicodeError:
            return _failure("invalid-content-encoding", status)
        if len(content_bytes) > request.max_content_bytes:
            return _failure("content-size-limit", status)
        try:
            _atomic_replace(request.repository, request.target_path, content_bytes)
            changed = _changed_paths(before, _snapshot(request.repository))
        except (OSError, RawApiError):
            return _failure("materialization-failed", status)
        if changed != {request.target_path}:
            return _failure("materialization-boundary-violation", status)
        return RawApiResult(
            outcome="ready-for-capture",
            reason_code="materialized",
            request_count=1,
            provider_status=status,
            materialized_path=request.target_path,
            final_repository=FinalRepositoryHandoff(
                condition="raw-api",
                repository=request.repository,
            ),
        )


def _request_completion(request: RawApiRequest) -> tuple[int, bytes]:
    parsed = urlsplit(request.proxy_base_url)
    path_prefix = "" if parsed.path in {"", "/"} else parsed.path
    body = canonical_json_bytes(
        {
            "messages": [
                {
                    "content": request.developer_brief.decode("utf-8", errors="strict"),
                    "role": "user",
                },
                {
                    "content": (
                        "Return only one JSON object with exactly path and content. "
                        f"path must be {json.dumps(request.target_path)}."
                    ),
                    "role": "system",
                },
            ],
            "model": request.model,
            # Streamed like every other condition (issue #99): a
            # non-streaming completion is silent until the whole generation
            # exists, and the cell's transparent egress relay drops
            # HTTP connections whose response stays silent past ~15s.
            # Still exactly one request; the deltas are assembled locally.
            "stream": True,
        }
    )
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=630)
    if not _connect_with_retry(connection):
        return 502, b""
    try:
        connection.request(
            "POST",
            f"{path_prefix}/chat/completions",
            body=body,
            headers={
                # http.client adds only Host and Content-Length; the
                # provider's WAF tarpits requests that don't look like a
                # normal API client (issue #99: missing UA/Accept). Send the
                # full, honest header shape of a streaming API client.
                "Accept": "text/event-stream, application/json",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {request.proxy_token}",
                "Content-Type": "application/json",
                "User-Agent": "model-benchmark-raw-api/1",
            },
        )
        response = connection.getresponse()
        status = response.status
        # SSE wraps every few content characters in its own JSON chunk, so
        # the stream is far larger than the assembled content it carries.
        limit = (
            request.max_content_bytes * _MAX_STREAM_EXPANSION
            + _MAX_PROVIDER_ENVELOPE_OVERHEAD
        )
        response_body = bytearray()
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            response_body += chunk
            if len(response_body) > limit:
                response.close()
                return 413, b""
        response.close()
    except (OSError, http.client.HTTPException):
        return 502, b""
    finally:
        connection.close()
    return status, bytes(response_body)


# The Trial Cell's proxy route can lag behind the main container under
# concurrent compose setup/teardown (issue #99: the raw-api cell always
# starts while sibling cells tear down, and its single stdlib client has
# no reconnect stack, unlike the harness runtimes). Retrying the local
# TCP connect carries zero provider interaction, so the one-request
# invariant is untouched.
_CONNECT_RETRY_SECONDS = 60.0
_CONNECT_RETRY_DELAY_SECONDS = 2.0


def _connect_with_retry(connection: http.client.HTTPConnection) -> bool:
    deadline = time.monotonic() + _CONNECT_RETRY_SECONDS
    while True:
        try:
            connection.connect()
            return True
        except OSError:
            connection.close()
            if time.monotonic() >= deadline:
                return False
            time.sleep(_CONNECT_RETRY_DELAY_SECONDS)


def _decode_provider_response(data: bytes) -> dict[str, object]:
    text = data.decode("utf-8", errors="strict")
    if _looks_like_sse(text):
        value: object = _assemble_sse_envelope(text)
    else:
        value = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise RawApiError("invalid-provider-envelope")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise RawApiError("invalid-provider-envelope")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise RawApiError("invalid-provider-envelope")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RawApiError("invalid-provider-envelope")
    if message.get("refusal") not in {None, ""}:
        raise RawApiError("provider-refusal")
    content = message.get("content")
    if not isinstance(content, str):
        raise RawApiError("provider-refusal")
    replacement = json.loads(content, object_pairs_hook=_unique_object)
    if not isinstance(replacement, dict) or set(replacement) != {"content", "path"}:
        raise RawApiError("invalid-materialization-envelope")
    if not isinstance(replacement["path"], str) or not isinstance(replacement["content"], str):
        raise RawApiError("invalid-materialization-envelope")
    return replacement


def _looks_like_sse(text: str) -> bool:
    return text.lstrip().startswith((":", "data:", "event:", "id:", "retry:"))


def _sse_payloads(text: str) -> Iterator[str]:
    """Yield data payloads using the EventSource field and event rules."""
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            value = ""
        elif value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        # EventSource ignores unknown fields. event/id/retry are metadata for
        # browser reconnection and do not alter an OpenAI response payload.
    if data_lines:
        yield "\n".join(data_lines)


def _invalid_sse(diagnostic_code: str) -> RawApiError:
    return RawApiError(
        "invalid-provider-envelope",
        diagnostic_code=diagnostic_code,
    )


def _decode_sse_choice(payload: str) -> dict[str, Any] | None:
    try:
        chunk = json.loads(payload, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise _invalid_sse("sse-invalid-json") from error
    if not isinstance(chunk, dict):
        raise _invalid_sse("sse-invalid-chunk")
    choices = chunk.get("choices")
    if not isinstance(choices, list) or len(choices) > 1:
        raise _invalid_sse("sse-invalid-choices")
    if not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        raise _invalid_sse("sse-invalid-choice")
    return choice


def _append_sse_choice(
    choice: dict[str, Any],
    role: str | None,
    refusal_parts: list[str],
    content_parts: list[str],
) -> tuple[str | None, bool]:
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and (
        not isinstance(finish_reason, str) or not finish_reason
    ):
        raise _invalid_sse("sse-invalid-finish-reason")
    delta = choice.get("delta")
    if delta is None:
        return role, finish_reason is not None
    if not isinstance(delta, dict):
        raise _invalid_sse("sse-invalid-delta")
    delta_role = delta.get("role")
    if delta_role is not None:
        if not isinstance(delta_role, str):
            raise _invalid_sse("sse-invalid-role")
        role = delta_role
    delta_refusal = delta.get("refusal")
    if delta_refusal is not None:
        if not isinstance(delta_refusal, str):
            raise _invalid_sse("sse-invalid-refusal")
        refusal_parts.append(delta_refusal)
    delta_content = delta.get("content")
    if delta_content is not None:
        if not isinstance(delta_content, str):
            raise _invalid_sse("sse-invalid-content")
        content_parts.append(delta_content)
    return role, finish_reason is not None


def _assemble_sse_envelope(text: str) -> dict[str, object]:
    """Fold one standards-framed OpenAI-compatible stream into a response."""
    role: str | None = None
    refusal_parts: list[str] = []
    content_parts: list[str] = []
    saw_done = False
    saw_finish_reason = False
    for payload in _sse_payloads(text):
        if payload == "[DONE]":
            if saw_done:
                raise _invalid_sse("sse-duplicate-terminator")
            saw_done = True
            continue
        choice = _decode_sse_choice(payload)
        if saw_done and choice is not None:
            raise _invalid_sse("sse-data-after-terminator")
        if saw_done or choice is None:
            # Standard usage-only and provider metadata trailers carry no choice.
            continue
        if saw_finish_reason:
            raise _invalid_sse("sse-choice-after-finish")
        role, saw_finish_reason = _append_sse_choice(
            choice, role, refusal_parts, content_parts
        )
    if not saw_done and not saw_finish_reason:
        raise _invalid_sse("sse-missing-terminator")
    return {
        "choices": [
            {
                "message": {
                    "content": "".join(content_parts),
                    "refusal": "".join(refusal_parts) or None,
                    "role": role or "assistant",
                },
            }
        ],
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise RawApiError("duplicate-json-field")
        value[key] = child
    return value


def _safe_target(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or "" in path.parts
        or path.as_posix() != value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise RawApiError("invalid-target-path")
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise RawApiError(f"unsafe repository entry: {relative}")
        if stat.S_ISREG(metadata.st_mode):
            files[relative] = path.read_bytes()
    return files


def _changed_paths(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    }


def _atomic_replace(root: Path, target_path: str, content: bytes) -> None:
    relative = _safe_target(target_path)
    target = root.joinpath(*relative.parts)
    parent = target.parent
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise RawApiError("unsafe-target-parent")
    if not target.exists() or target.is_symlink() or not target.is_file():
        raise RawApiError("target-must-be-existing-regular-file")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, target.stat().st_mode & 0o777)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _failure(
    reason_code: str,
    status: int | None,
    *,
    diagnostic_code: str | None = None,
) -> RawApiResult:
    return RawApiResult(
        outcome="valid_harness_outcome",
        reason_code=reason_code,
        request_count=1,
        provider_status=status,
        materialized_path=None,
        final_repository=None,
        diagnostic_code=diagnostic_code,
    )
