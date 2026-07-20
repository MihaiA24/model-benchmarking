"""Sealed repo artifacts stay byte-canonical (issue #112).

Condition locks and scenario locks are byte-hashed canonical JSON: every
digest over them breaks if an editor reformats the file, yet the
resulting ``CanonicalizationError`` surfaces at conformance *collection*
time and names neither the damaged file nor the remedy, while the
default development slice stays green. This gate turns working-tree
byte damage into a named, actionable development-gate failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    load_canonical_json,
)
from model_benchmark.runtime.condition_registry import CONDITIONS

ROOT = Path(__file__).resolve().parents[2]


def _sealed_artifact_paths() -> tuple[Path, ...]:
    condition_locks = tuple(
        definition.lock_path() for definition in CONDITIONS.values()
    )
    scenario_locks = tuple(sorted((ROOT / "scenarios").rglob("scenario.lock.json")))
    return condition_locks + scenario_locks


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("path", _sealed_artifact_paths(), ids=_relative)
def test_sealed_artifact_bytes_are_canonical(path: Path) -> None:
    try:
        load_canonical_json(path.read_bytes())
    except CanonicalizationError as error:
        pytest.fail(
            f"{_relative(path)} is not canonical JSON ({error}); sealed "
            "artifacts are byte-hashed, so reformatting (editor "
            "format-on-save is the usual culprit) breaks every digest over "
            f"them. Restore the sealed bytes: git restore {_relative(path)}"
        )


def test_sealed_artifact_inventory_covers_registry_and_scenarios() -> None:
    paths = _sealed_artifact_paths()
    relative = {_relative(path) for path in paths}
    assert len(paths) == len(relative)
    for definition in CONDITIONS.values():
        assert _relative(definition.lock_path()) in relative
    assert any(item.startswith("scenarios/") for item in relative), (
        "no scenario locks found; the sealed-artifact inventory is vacuous"
    )
