from __future__ import annotations

import ast
from pathlib import Path


PUBLIC_HARBOR_ADAPTER_IMPORTS = frozenset(
    {
        "harbor.agents.installed.base",
        "harbor.agents.installed.base.BaseInstalledAgent",
    }
)


def import_candidates(path: Path, source_parent: Path) -> set[str]:
    """Return normalized module candidates represented by a Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    relative_module = path.relative_to(source_parent).with_suffix("")
    package_parts = list(relative_module.parts)
    if path.name != "__init__.py":
        package_parts.pop()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0 and node.module is not None:
            base = node.module
        else:
            if node.level > len(package_parts):
                raise ValueError(
                    f"relative import escapes source root: {path}:{node.lineno}"
                )
            base_parts = package_parts[: len(package_parts) - node.level + 1]
            if node.module is not None:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
        for alias in node.names:
            imported.add(f"{base}.*" if alias.name == "*" else f"{base}.{alias.name}")
    return imported


def harbor_import_is_allowed(path: Path, adapter_root: Path, imported: str) -> bool:
    """Return whether a Harbor import uses only the supported Adapter contract."""
    return path.is_relative_to(adapter_root) and imported in PUBLIC_HARBOR_ADAPTER_IMPORTS
