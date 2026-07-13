#!/usr/bin/env python3
"""Trusted, sidecar-local capture used only by the Harbor seam proof."""

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


SCHEMA_VERSION = "proof-capture-v1"
SAFE_PATCH_PATH = re.compile(r"[A-Za-z0-9._/-]+")


class CaptureRejected(Exception):
    """The repository cannot cross the Submission boundary."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CapturePolicy(TypedDict):
    allowed_paths: list[str]
    max_file_count: int
    max_total_bytes: int
    stability_window_ms: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _is_allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _snapshot(root: Path, policy: CapturePolicy) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise CaptureRejected("invalid_repository_root")

    allowed = policy["allowed_paths"]
    max_files = policy["max_file_count"]
    max_bytes = policy["max_total_bytes"]
    files: dict[str, bytes] = {}
    total_bytes = 0
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
            if not _is_allowed(relative, allowed):
                raise CaptureRejected("undeclared_path")
            if metadata.st_nlink != 1:
                raise CaptureRejected("hard_link")
            if len(files) + 1 > max_files:
                raise CaptureRejected("file_count_limit")
            if total_bytes + metadata.st_size > max_bytes:
                raise CaptureRejected("byte_limit")

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
            total_bytes += len(data)

    return dict(sorted(files.items()))


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
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("capture.json", "submission.patch"):
        (args.output / name).unlink(missing_ok=True)

    policy = cast(
        CapturePolicy,
        json.loads(args.policy.read_text(encoding="utf-8")),
    )
    try:
        baseline = _snapshot(args.baseline, policy)
        first = _snapshot(args.repository, policy)
        time.sleep(policy["stability_window_ms"] / 1000)
        second = _snapshot(args.repository, policy)
        if first != second:
            raise CaptureRejected("repository_changed_during_capture")
        patch = _normalized_patch(baseline, second)
    except CaptureRejected as exc:
        _reject(args.output, args.policy, exc.code)

    _atomic_write(args.output / "submission.patch", patch)
    record = {
        "baseline_sha256": _tree_digest(baseline),
        "collector": _collector_identity(args.policy),
        "file_count": len(second),
        "final_sha256": _tree_digest(second),
        "kind": "no-op" if not patch else "patch",
        "patch_sha256": _sha256(patch),
        "schema_version": SCHEMA_VERSION,
        "stability_window_ms": policy["stability_window_ms"],
        "status": "accepted",
        "total_bytes": sum(len(data) for data in second.values()),
    }
    _atomic_write(args.output / "capture.json", _canonical_json(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
