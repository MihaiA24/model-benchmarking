from __future__ import annotations

import http.client
import json
import os
import stat
import tempfile
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


class RawApiError(ValueError):
    """The Raw API condition declaration is unsafe or internally inconsistent."""


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
        except (UnicodeError, json.JSONDecodeError, RawApiError) as error:
            reason = str(error) if isinstance(error, RawApiError) else "invalid-provider-json"
            return _failure(reason, status)
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
            "stream": False,
        }
    )
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=30)
    try:
        connection.request(
            "POST",
            f"{path_prefix}/chat/completions",
            body=body,
            headers={
                "Authorization": f"Bearer {request.proxy_token}",
                "Content-Type": "application/json",
                # http.client sends no User-Agent by default; the provider's
                # WAF tarpits UA-less requests (issue #99). Identify honestly.
                "User-Agent": "model-benchmark-raw-api/1",
            },
        )
        response = connection.getresponse()
        limit = request.max_content_bytes + _MAX_PROVIDER_ENVELOPE_OVERHEAD
        response_body = response.read(limit + 1)
        status = response.status
        response.close()
    except (OSError, http.client.HTTPException):
        return 502, b""
    finally:
        connection.close()
    if len(response_body) > limit:
        return 413, b""
    return status, response_body


def _decode_provider_response(data: bytes) -> dict[str, object]:
    value = json.loads(
        data.decode("utf-8", errors="strict"),
        object_pairs_hook=_unique_object,
    )
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


def _failure(reason_code: str, status: int | None) -> RawApiResult:
    return RawApiResult(
        outcome="valid_harness_outcome",
        reason_code=reason_code,
        request_count=1,
        provider_status=status,
        materialized_path=None,
        final_repository=None,
    )
