"""Workdir creation and task seeding."""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import subprocess
from pathlib import Path

from benchmark.util import repo_path



def _force_remove(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onerror=_force_remove)


def _link_node_modules(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"node_modules not found: {src}")
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True, capture_output=True)
    else:
        dst.symlink_to(src, target_is_directory=True)


def _clone_file(src: str, dst: str) -> bool:
    if os.name != "posix" or os.uname().sysname != "Darwin":
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.clonefile(src.encode(), dst.encode(), 0) == 0:
        return True
    return False


def _clone_or_copy_file(src: str, dst: str) -> str:
    if _clone_file(src, dst):
        shutil.copystat(src, dst)
        return dst
    return shutil.copy2(src, dst)


def clone_tree(src: Path, dst: Path) -> None:
    """Copy a tree, using APFS copy-on-write file clones when available."""
    shutil.copytree(src, dst, symlinks=True, copy_function=_clone_or_copy_file)


def task_snapshot_path(cache_dir: Path, task) -> Path:
    return cache_dir / task.name


def _populate_workdir(task, workdir: Path, *, apply_task_seed: bool = True) -> None:
    baseline = repo_path(task.baseline)
    if not baseline.exists():
        raise FileNotFoundError(f"Baseline not found for {task.name}: {baseline}")
    ignore = shutil.ignore_patterns(*task.copy_ignore) if task.copy_ignore else None
    shutil.copytree(baseline, workdir, ignore=ignore)
    if task.link_node_modules:
        _link_node_modules(baseline / "node_modules", workdir / "node_modules")
    if apply_task_seed:
        apply_seed(task, workdir)


def prepare_task_snapshot(task, cache_dir: Path, *, refresh: bool = False) -> Path:
    snapshot = task_snapshot_path(cache_dir, task)
    if refresh:
        remove_tree(snapshot)
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        _populate_workdir(task, snapshot)
    return snapshot


def make_workdir(task, workdir: Path, *, cache_dir: Path | None = None) -> None:
    remove_tree(workdir)
    if cache_dir is None:
        _populate_workdir(task, workdir)
        return
    snapshot = prepare_task_snapshot(task, cache_dir)
    clone_tree(snapshot, workdir)


def make_clean_baseline_workdir(task, workdir: Path) -> None:
    """Create a workdir from the clean baseline, without task seed patches/files."""
    remove_tree(workdir)
    _populate_workdir(task, workdir, apply_task_seed=False)


def apply_seed(task, workdir: Path) -> None:
    for rel, (old, new) in task.seed_patches.items():
        path = workdir / rel
        content = path.read_text(encoding="utf-8")
        if old not in content:
            raise ValueError(f"Patch string not found in {rel}: {old[:80]!r}")
        path.write_text(content.replace(old, new, 1), encoding="utf-8")
    for rel, content in task.new_files.items():
        path = workdir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
