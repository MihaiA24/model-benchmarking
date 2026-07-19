from __future__ import annotations

import sys
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


def test_runtime_modules_do_not_import_developer_verification() -> None:
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "runtime").rglob("*.py")):
        for imported in _imports(path):
            if imported == "verification" or imported.startswith("verification."):
                violations.append(
                    f"{path.relative_to(ROOT)}: runtime imports {imported}"
                )
    assert violations == []


def _first_party_module_file(candidate: str) -> Path | None:
    parts = candidate.split(".")
    for length in range(len(parts), 0, -1):
        base = ROOT / "src" / Path(*parts[:length])
        for path in (base.with_suffix(".py"), base / "__init__.py"):
            if path.is_file():
                return path
    return None


def _package_init_files(path: Path) -> list[Path]:
    inits: list[Path] = []
    for parent in path.parents:
        if not parent.is_relative_to(SOURCE_ROOT):
            break
        init = parent / "__init__.py"
        if init.is_file() and init != path:
            inits.append(init)
    return inits


def _stdlib_only_closure_violations(entry: Path) -> list[str]:
    pending = [entry]
    seen: set[Path] = set()
    violations: list[str] = []
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        pending.extend(_package_init_files(path))
        for imported in sorted(_imports(path)):
            top = imported.split(".", 1)[0]
            if top == "model_benchmark":
                resolved = _first_party_module_file(imported)
                if resolved is not None:
                    pending.append(resolved)
                continue
            if top not in sys.stdlib_module_names:
                violations.append(f"{path.relative_to(ROOT)}: {imported}")
    return violations


def test_credential_proxy_service_import_closure_is_stdlib_only() -> None:
    # The sealed credential-proxy image is a bare Python base plus the copied
    # model_benchmark tree: no third-party distribution exists inside it, so
    # any non-stdlib import in the service's closure crashes the container
    # before it can serve /healthz.
    assert _stdlib_only_closure_violations(
        SOURCE_ROOT / "runtime/credential_proxy_service.py"
    ) == []


def test_condition_image_import_closure_is_stdlib_only() -> None:
    # The condition entrypoint runs the copied model_benchmark tree with the
    # mounted python's bare stdlib (PYTHONPATH=/opt/model-benchmark-runtime,
    # no third-party distributions). Any heavier import in the closure of
    # condition_image kills every default-entrypoint condition inside the
    # cell before its first provider request — invisible to host-venv test
    # runs, where the dependency exists (issue #99).
    assert _stdlib_only_closure_violations(
        SOURCE_ROOT / "runtime/condition_image.py"
    ) == []
