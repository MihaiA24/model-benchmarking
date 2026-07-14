#!/usr/bin/env python3
"""Trusted standard-v1 sidecar capture for Scenario Package submissions."""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path, PurePosixPath
from typing import NoReturn, TypedDict, cast


SCHEMA_VERSION = "scenario-capture-v1"
SAFE_PATCH_PATH = re.compile(r"[A-Za-z0-9._/-]+")


class CaptureRejected(Exception):
    """The repository cannot cross the Submission boundary."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CapturePolicy(TypedDict):
    allowed_paths: list[str]
    protected_paths: list[str]
    allow_additions: bool
    allow_deletions: bool
    forbidden_markers: list[str]
    max_file_count: int
    max_total_bytes: int
    stability_window_ms: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _is_allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def trusted_capture_source() -> str:
    """Return the evidence-owned executable copied into a Scenario Package."""
    return Path(__file__).read_text(encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise CaptureRejected("invalid_repository_root")

    files: dict[str, bytes] = {}
    pending = [root]

    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise CaptureRejected("repository_unreadable") from exc

        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            pure = PurePosixPath(relative)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or "" in pure.parts
                or SAFE_PATCH_PATH.fullmatch(relative) is None
            ):
                raise CaptureRejected("unsafe_path")
            if relative == ".git":
                continue
            if ".git" in pure.parts:
                raise CaptureRejected("nested_repository")

            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CaptureRejected("repository_unreadable") from exc

            if stat.S_ISLNK(metadata.st_mode):
                raise CaptureRejected("symlink")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise CaptureRejected("special_file")
            unsafe_mode = metadata.st_mode & (
                stat.S_ISUID
                | stat.S_ISGID
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )
            if unsafe_mode:
                raise CaptureRejected("unsafe_mode")
            if metadata.st_nlink != 1:
                raise CaptureRejected("hard_link")

            try:
                data = path.read_bytes()
            except OSError as exc:
                raise CaptureRejected("repository_unreadable") from exc
            if len(data) != metadata.st_size:
                raise CaptureRejected("repository_changed_during_capture")
            if b"\x00" in data:
                raise CaptureRejected("binary_file")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CaptureRejected("non_utf8_file") from exc

            files[relative] = data

    return dict(sorted(files.items()))


def _validate_changes(
    baseline: dict[str, bytes],
    candidate: dict[str, bytes],
    policy: CapturePolicy,
) -> tuple[list[str], int]:
    changed: list[str] = []
    changed_bytes = 0
    for path in sorted(set(baseline) | set(candidate)):
        before = baseline.get(path)
        after = candidate.get(path)
        if before == after:
            continue
        if _is_allowed(path, policy["protected_paths"]):
            raise CaptureRejected("protected_path")
        if not _is_allowed(path, policy["allowed_paths"]):
            raise CaptureRejected("undeclared_path")
        if before is None and not policy["allow_additions"]:
            raise CaptureRejected("addition_forbidden")
        if after is None and not policy["allow_deletions"]:
            raise CaptureRejected("deletion_forbidden")
        changed.append(path)
        changed_bytes += max(len(before or b""), len(after or b""))
    if len(changed) > policy["max_file_count"]:
        raise CaptureRejected("file_count_limit")
    if changed_bytes > policy["max_total_bytes"]:
        raise CaptureRejected("byte_limit")
    return changed, changed_bytes


def _validate_hidden_markers(
    candidate: dict[str, bytes], policy: CapturePolicy
) -> list[str]:
    digests: list[str] = []
    for marker in policy["forbidden_markers"]:
        encoded = marker.encode("utf-8")
        digests.append(_sha256(encoded))
        if any(encoded in content for content in candidate.values()):
            raise CaptureRejected("hidden_marker_exposed")
    return sorted(digests)


def _scan_hidden_markers(root: Path, markers: list[str]) -> list[str]:
    if not root.is_dir() or root.is_symlink():
        raise CaptureRejected("invalid_repository_root")
    encoded = [
        (marker.encode("utf-8"), _sha256(marker.encode("utf-8")))
        for marker in markers
    ]
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError as exc:
            raise CaptureRejected("repository_unreadable") from exc
        with entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        raise CaptureRejected("symlink")
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    content = Path(entry.path).read_bytes()
                except OSError as exc:
                    raise CaptureRejected("repository_unreadable") from exc
                if any(marker in content for marker, _ in encoded):
                    raise CaptureRejected("hidden_marker_exposed")
    return sorted(digest for _, digest in encoded)


def _tree_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, data in sorted(files.items()):
        encoded_path = path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8").splitlines(keepends=True)


def _normalized_patch(
    baseline: dict[str, bytes], candidate: dict[str, bytes]
) -> bytes:
    chunks: list[str] = []
    for path in sorted(set(baseline) | set(candidate)):
        before = baseline.get(path)
        after = candidate.get(path)
        if before == after:
            continue

        chunks.append(f"diff --git a/{path} b/{path}\n")
        if before is None:
            chunks.append("new file mode 100644\n")
        elif after is None:
            chunks.append("deleted file mode 100644\n")

        from_name = f"a/{path}" if before is not None else "/dev/null"
        to_name = f"b/{path}" if after is not None else "/dev/null"
        diff_lines = difflib.unified_diff(
            _lines(before or b""),
            _lines(after or b""),
            fromfile=from_name,
            tofile=to_name,
            lineterm="\n",
        )
        for line in diff_lines:
            if line.endswith("\n"):
                chunks.append(line)
            else:
                chunks.extend((line, "\n\\ No newline at end of file\n"))
    return "".join(chunks).encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    if path.read_bytes() != data:
        raise RuntimeError(f"read-back mismatch for {path.name}")


def _read_regular_no_follow(root: Path, path: Path, max_bytes: int) -> bytes:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise CaptureRejected("unsafe_artifact") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise CaptureRejected("unsafe_artifact")
    descriptors: list[int] = []
    try:
        directory_descriptor = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptors.append(directory_descriptor)
        for component in relative.parts[:-1]:
            directory_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            descriptors.append(directory_descriptor)
        descriptor = os.open(
            relative.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptor,
        )
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise CaptureRejected("unsafe_artifact")
        if metadata.st_size > max_bytes:
            raise CaptureRejected("byte_limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != metadata.st_size or len(data) > max_bytes:
            raise CaptureRejected("artifact_changed_during_capture")
        return data
    except OSError as exc:
        raise CaptureRejected("artifact_unreadable") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _capture_artifact(args: argparse.Namespace) -> int:
    required = (
        "artifact_output",
        "artifact_record",
        "artifact_media_type",
        "artifact_schema_sha256",
        "artifact_max_bytes",
        "visibility_root",
        "forbidden_marker",
    )
    if any(getattr(args, field) is None for field in required):
        raise CaptureRejected("invalid_artifact_policy")
    first = _read_regular_no_follow(
        args.visibility_root, args.artifact_source, args.artifact_max_bytes
    )
    time.sleep(args.stability_window_ms / 1000)
    second = _read_regular_no_follow(
        args.visibility_root, args.artifact_source, args.artifact_max_bytes
    )
    if first != second:
        raise CaptureRejected("artifact_changed_during_capture")
    if args.artifact_media_type == "application/json":
        try:
            json.loads(second)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureRejected("malformed_artifact") from exc
    marker_digests = _scan_hidden_markers(
        args.visibility_root,
        args.forbidden_marker,
    )
    _atomic_write(args.artifact_output, second)
    record = {
        "artifact_sha256": _sha256(second),
        "hidden_markers": {"digests": marker_digests, "status": "absent"},
        "media_type": args.artifact_media_type,
        "mode": "copy-no-follow",
        "schema_sha256": args.artifact_schema_sha256,
        "source": str(args.artifact_source),
        "status": "accepted",
        "total_bytes": len(second),
    }
    _atomic_write(args.artifact_record, _canonical_json(record))
    return 0


def _collector_identity(policy_path: Path) -> dict[str, str]:
    return {
        "capture_source_sha256": _sha256(Path(__file__).read_bytes()),
        "policy_sha256": _sha256(policy_path.read_bytes()),
    }


def _reject(output: Path, policy_path: Path, code: str) -> NoReturn:
    record = {
        "collector": _collector_identity(policy_path),
        "reason": code,
        "schema_version": SCHEMA_VERSION,
        "status": "rejected",
    }
    _atomic_write(output / "capture.json", _canonical_json(record))
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--repository", type=Path)
    mode.add_argument("--artifact-source", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-output", type=Path)
    parser.add_argument("--artifact-record", type=Path)
    parser.add_argument("--artifact-media-type")
    parser.add_argument("--artifact-schema-sha256")
    parser.add_argument("--artifact-max-bytes", type=int)
    parser.add_argument("--visibility-root", type=Path)
    parser.add_argument("--forbidden-marker", action="append")
    parser.add_argument("--stability-window-ms", type=int, default=250)
    args = parser.parse_args()

    if args.artifact_source is not None:
        try:
            return _capture_artifact(args)
        except CaptureRejected as exc:
            if args.artifact_record is not None:
                args.artifact_record.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(
                    args.artifact_record,
                    _canonical_json({"reason": exc.code, "status": "rejected"}),
                )
            return 2
    if args.baseline is None or args.policy is None or args.output is None:
        parser.error("patch capture requires --baseline, --policy, and --output")

    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("capture.json", "submission.patch"):
        (args.output / name).unlink(missing_ok=True)

    policy = cast(
        CapturePolicy,
        json.loads(args.policy.read_text(encoding="utf-8")),
    )
    try:
        baseline = _snapshot(args.baseline)
        first = _snapshot(args.repository)
        time.sleep(policy["stability_window_ms"] / 1000)
        second = _snapshot(args.repository)
        if first != second:
            raise CaptureRejected("repository_changed_during_capture")
        changed, changed_bytes = _validate_changes(baseline, second, policy)
        marker_digests = _validate_hidden_markers(second, policy)
        patch = _normalized_patch(baseline, second)
    except CaptureRejected as exc:
        _reject(args.output, args.policy, exc.code)

    _atomic_write(args.output / "submission.patch", patch)
    record = {
        "baseline_sha256": _tree_digest(baseline),
        "collector": _collector_identity(args.policy),
        "file_count": len(changed),
        "final_sha256": _tree_digest(second),
        "hidden_markers": {"digests": marker_digests, "status": "absent"},
        "kind": "no-op" if not patch else "patch",
        "patch_sha256": _sha256(patch),
        "schema_version": SCHEMA_VERSION,
        "stability_window_ms": policy["stability_window_ms"],
        "status": "accepted",
        "total_bytes": changed_bytes,
    }
    _atomic_write(args.output / "capture.json", _canonical_json(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
