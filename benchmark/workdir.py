"""Workdir creation and task seeding."""

from __future__ import annotations

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


def make_workdir(task, workdir: Path) -> None:
    remove_tree(workdir)
    baseline = repo_path(task.baseline)
    if not baseline.exists():
        raise FileNotFoundError(f"Baseline not found for {task.name}: {baseline}")
    ignore = shutil.ignore_patterns(*task.copy_ignore) if task.copy_ignore else None
    shutil.copytree(baseline, workdir, ignore=ignore)
    if task.link_node_modules:
        _link_node_modules(baseline / "node_modules", workdir / "node_modules")
    apply_seed(task, workdir)


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
