from __future__ import annotations

from pathlib import Path

import pytest

from model_benchmark.evidence.imports import (
    harbor_import_is_allowed,
    import_candidates,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src/model_benchmark"
REVERSE_IMPORTS = {
    "declarations": {"analysis", "evidence", "runtime"},
    "runtime": {"analysis", "evidence"},
    "evidence": {"analysis", "runtime"},
    "analysis": set(),
}


def _imports(path: Path, source_parent: Path = ROOT / "src") -> set[str]:
    return import_candidates(path, source_parent)


def test_relative_imports_are_normalized_before_guarding(tmp_path: Path) -> None:
    source_parent = tmp_path / "src"
    path = source_parent / "model_benchmark/declarations/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("from ..runtime import execute\n", encoding="utf-8")

    assert _imports(path, source_parent) == {"model_benchmark.runtime.execute"}


def test_relative_imports_cannot_escape_the_source_root(tmp_path: Path) -> None:
    source_parent = tmp_path / "src"
    path = source_parent / "model_benchmark/declarations/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("from ...outside import value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="relative import escapes source root"):
        _imports(path, source_parent)


def test_import_from_aliases_expose_effective_dependency_candidates(
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "src"
    path = source_parent / "model_benchmark/declarations/example.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from model_benchmark import runtime\n"
        "from .. import evidence\n"
        "from harbor.agents.installed import base\n"
        "from harbor.agents.installed.base import BaseInstalledAgent\n",
        encoding="utf-8",
    )

    assert _imports(path, source_parent) == {
        "model_benchmark.runtime",
        "model_benchmark.evidence",
        "harbor.agents.installed.base",
        "harbor.agents.installed.base.BaseInstalledAgent",
    }


def test_harbor_aliases_are_allowed_only_inside_the_public_adapter_seam(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src/model_benchmark"
    adapter_root = source_root / "runtime/adapters"
    inside = adapter_root / "example.py"
    outside = source_root / "declarations/example.py"

    assert harbor_import_is_allowed(
        inside,
        adapter_root,
        "harbor.agents.installed.base.BaseInstalledAgent",
    )
    assert not harbor_import_is_allowed(
        outside,
        adapter_root,
        "harbor.agents.installed.base.BaseInstalledAgent",
    )
    assert not harbor_import_is_allowed(
        inside,
        adapter_root,
        "harbor.agents.installed.private.InternalAgent",
    )
    assert not harbor_import_is_allowed(
        inside,
        adapter_root,
        "harbor.agents.installed.base.InternalAgent",
    )

    wildcard = source_root / "runtime/adapters/wildcard.py"
    wildcard.parent.mkdir(parents=True)
    wildcard.write_text(
        "from harbor.agents.installed.base import *\n",
        encoding="utf-8",
    )
    wildcard_imports = _imports(wildcard, tmp_path / "src")
    assert wildcard_imports == {"harbor.agents.installed.base.*"}
    assert all(
        not harbor_import_is_allowed(wildcard, adapter_root, imported)
        for imported in wildcard_imports
    )


def test_public_module_dependencies_never_point_backwards() -> None:
    violations: list[str] = []
    for owner, forbidden_modules in REVERSE_IMPORTS.items():
        for path in sorted((SOURCE_ROOT / owner).rglob("*.py")):
            for imported in _imports(path):
                for forbidden in forbidden_modules:
                    prefix = f"model_benchmark.{forbidden}"
                    if imported == prefix or imported.startswith(prefix + "."):
                        violations.append(
                            f"{path.relative_to(ROOT)}: {owner} imports {imported}"
                        )
    assert violations == []


def test_harbor_imports_are_confined_to_supported_adapter_seam() -> None:
    violations: list[str] = []
    adapter_root = SOURCE_ROOT / "runtime/adapters"
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            if imported != "harbor" and not imported.startswith("harbor."):
                continue
            if not harbor_import_is_allowed(path, adapter_root, imported):
                violations.append(f"{path.relative_to(ROOT)}: forbidden import {imported}")
    assert violations == []
