from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src/model_benchmark"
REVERSE_IMPORTS = {
    "declarations": {"analysis", "evidence", "runtime"},
    "runtime": {"analysis", "evidence"},
    "evidence": {"analysis", "runtime"},
    "analysis": set(),
}
PUBLIC_HARBOR_ADAPTER_IMPORT = "harbor.agents.installed.base"


def _imports(path: Path, source_parent: Path = ROOT / "src") -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    relative_module = path.relative_to(source_parent).with_suffix("")
    package_parts = list(relative_module.parts)
    if path.name != "__init__.py":
        package_parts.pop()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                imported.add(node.module)
                continue
            if node.level > len(package_parts):
                imported.add("<invalid-relative-import>")
                continue
            base = package_parts[: len(package_parts) - node.level + 1]
            if node.module is not None:
                base.extend(node.module.split("."))
            imported.add(".".join(base))
    return imported


def test_relative_imports_are_normalized_before_guarding(tmp_path: Path) -> None:
    source_parent = tmp_path / "src"
    path = source_parent / "model_benchmark/declarations/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("from ..runtime import execute\n", encoding="utf-8")

    assert _imports(path, source_parent) == {"model_benchmark.runtime"}


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
            inside_adapter = path.is_relative_to(adapter_root)
            if not inside_adapter or imported != PUBLIC_HARBOR_ADAPTER_IMPORT:
                violations.append(f"{path.relative_to(ROOT)}: forbidden import {imported}")
    assert violations == []
