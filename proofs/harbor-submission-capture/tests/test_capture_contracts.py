from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest


PROOF_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_PATH = PROOF_ROOT / "fixtures/task/environment/capture/capture.py"


def _capture_namespace() -> dict[str, Any]:
    return runpy.run_path(str(CAPTURE_PATH))


def test_normalized_patch_is_git_apply_safe_without_trailing_newline(
    tmp_path: Path,
) -> None:
    namespace = _capture_namespace()
    normalized_patch = namespace["_normalized_patch"]
    patch = normalized_patch(
        {"src/app.txt": b"before"},
        {"src/app.txt": b"after"},
    )

    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / "src/app.txt").write_bytes(b"before")
    patch_path = tmp_path / "submission.patch"
    patch_path.write_bytes(patch)

    checked = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr


def test_capture_rejects_patch_header_control_characters(tmp_path: Path) -> None:
    namespace = _capture_namespace()
    snapshot = namespace["_snapshot"]
    rejected = namespace["CaptureRejected"]

    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / "src" / "bad\nname.txt").write_text("unsafe\n", encoding="utf-8")
    policy = {
        "allowed_paths": ["src/**"],
        "max_file_count": 16,
        "max_total_bytes": 1024,
        "stability_window_ms": 0,
    }

    with pytest.raises(rejected) as error:
        snapshot(repository, policy)
    assert error.value.code == "unsafe_path"
