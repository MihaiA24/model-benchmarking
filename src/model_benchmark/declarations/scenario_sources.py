from __future__ import annotations

import hashlib
import os
import stat
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from model_benchmark.declarations.identities import DigestKind, TypedDigest


_MAX_ARCHIVE_FILES = 100_000
_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


class ScenarioSourceError(ValueError):
    """The pristine snapshot or seeded Scenario Baseline did not reproduce."""


def _portable_relative_path(value: str, label: str) -> str:
    normalized_input = value.rstrip("/")
    path = PurePosixPath(normalized_input)
    if (
        not normalized_input
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or path.as_posix() != normalized_input
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ScenarioSourceError(f"{label} is not a normalized portable path: {value}")
    return normalized_input


def normalized_tree_digest(root: Path) -> TypedDigest:
    """Hash sorted regular-file paths and bytes; reject non-portable trees."""
    digest = hashlib.sha256()
    relative_paths: set[str] = set()
    casefolded_paths: set[str] = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ScenarioSourceError(f"source tree cannot contain symlinks: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ScenarioSourceError(f"source tree path is not regular: {path}")
        relative_text = _portable_relative_path(
            path.relative_to(root).as_posix(),
            "source tree path",
        )
        if relative_text in relative_paths or relative_text.casefold() in casefolded_paths:
            raise ScenarioSourceError(f"source tree path collides by case: {relative_text}")
        relative_paths.add(relative_text)
        casefolded_paths.add(relative_text.casefold())
        relative = relative_text.encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return TypedDigest(DigestKind.SOURCE_TREE, digest.hexdigest())


def _extract_pristine(archive_path: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = archive.getmembers()
            if len(members) > _MAX_ARCHIVE_FILES:
                raise ScenarioSourceError("pristine archive has too many entries")
            total = 0
            paths: set[str] = set()
            casefolded: set[str] = set()
            for member in members:
                normalized = _portable_relative_path(
                    member.name,
                    "pristine archive member",
                )
                if (
                    member.issym()
                    or member.islnk()
                    or not (member.isfile() or member.isdir())
                ):
                    raise ScenarioSourceError(
                        f"unsafe pristine archive member: {member.name}"
                    )
                if normalized in paths or normalized.casefold() in casefolded:
                    raise ScenarioSourceError(
                        f"pristine archive path collides: {member.name}"
                    )
                paths.add(normalized)
                casefolded.add(normalized.casefold())
                total += member.size
                if total > _MAX_ARCHIVE_BYTES:
                    raise ScenarioSourceError("pristine archive is oversized")
            archive.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise ScenarioSourceError(f"cannot extract pristine archive: {error}") from error


def _apply_seed_patch(root: Path, patch_path: Path) -> None:
    commands = (
        ["git", "apply", "--check", "--whitespace=nowarn", str(patch_path)],
        ["git", "apply", "--whitespace=nowarn", str(patch_path)],
    )
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ScenarioSourceError(f"seed patch execution failed: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ScenarioSourceError(f"seed patch does not apply cleanly: {detail}")


def _verify_artifact_digest(path: Path, expected: str, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ScenarioSourceError(f"{label} is not a regular file: {path}")
    try:
        actual = str(TypedDigest.from_bytes(DigestKind.ARTIFACT, path.read_bytes()))
    except OSError as error:
        raise ScenarioSourceError(f"cannot read {label}: {error}") from error
    if actual != expected:
        raise ScenarioSourceError(f"{label} digest mismatch")


def _apply_seed_asset(root: Path, asset_path: Path, destination: str) -> None:
    relative = PurePosixPath(
        _portable_relative_path(destination, "seed asset destination")
    )
    try:
        data = asset_path.read_bytes()
        root_descriptor = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise ScenarioSourceError(f"cannot read seed asset {relative}: {error}") from error
    descriptors = [root_descriptor]
    target_descriptor: int | None = None
    try:
        directory_descriptor = root_descriptor
        for component in relative.parts[:-1]:
            try:
                os.mkdir(component, mode=0o755, dir_fd=directory_descriptor)
            except FileExistsError:
                pass
            directory_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            descriptors.append(directory_descriptor)
        target_descriptor = os.open(
            relative.name,
            os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o644,
            dir_fd=directory_descriptor,
        )
        metadata = os.fstat(target_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ScenarioSourceError(f"seed asset destination is unsafe: {relative}")
        os.ftruncate(target_descriptor, 0)
        view = memoryview(data)
        while view:
            written = os.write(target_descriptor, view)
            if written <= 0:
                raise OSError("short seed asset write")
            view = view[written:]
    except (OSError, ScenarioSourceError) as error:
        if isinstance(error, ScenarioSourceError):
            raise
        raise ScenarioSourceError(f"cannot apply seed asset {relative}: {error}") from error
    finally:
        if target_descriptor is not None:
            os.close(target_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def verify_source_reconstruction(package: Path, manifest: dict[str, Any]) -> None:
    """Reproduce pristine and baseline identities without network or setup scripts."""
    repository = manifest["repository"]
    pristine = repository["pristine"]
    archive = pristine["archive"]
    seed_inputs = repository["seed_inputs"]
    if archive is None:
        empty = str(
            TypedDigest(DigestKind.SOURCE_TREE, hashlib.sha256().hexdigest())
        )
        if seed_inputs:
            raise ScenarioSourceError("seed inputs require a pristine source archive")
        if pristine["tree_sha256"] != empty or repository["baseline_tree_sha256"] != empty:
            raise ScenarioSourceError(
                "non-empty source identity requires a pristine source archive"
            )
        return

    archive_path = package / archive
    _verify_artifact_digest(
        archive_path,
        pristine["archive_sha256"],
        "Pristine Source Snapshot archive",
    )
    with tempfile.TemporaryDirectory(prefix="scenario-source-") as temporary:
        temporary_root = Path(temporary)
        pristine_root = temporary_root / "pristine"
        baseline_root = temporary_root / "baseline"
        pristine_root.mkdir()
        _extract_pristine(archive_path, pristine_root)
        actual_pristine = str(normalized_tree_digest(pristine_root))
        if actual_pristine != pristine["tree_sha256"]:
            raise ScenarioSourceError("Pristine Source Snapshot tree digest mismatch")
        shutil.copytree(pristine_root, baseline_root)
        for seed in seed_inputs:
            seed_path = package / seed["path"]
            _verify_artifact_digest(seed_path, seed["sha256"], "seed input")
            if seed["kind"] == "git-patch":
                _apply_seed_patch(baseline_root, seed_path)
            elif seed["kind"] == "asset":
                _apply_seed_asset(baseline_root, seed_path, seed["destination"])
            else:
                raise ScenarioSourceError(f"unsupported seed kind: {seed['kind']}")
        actual_baseline = str(normalized_tree_digest(baseline_root))
        if actual_baseline != repository["baseline_tree_sha256"]:
            raise ScenarioSourceError("Scenario Baseline tree digest mismatch")
