from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_sources import (
    ScenarioSourceError,
    _apply_seed_asset,
    normalized_tree_digest,
)


CLI = Path(sys.executable).with_name("model-benchmark")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, "--json", "scenario", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _artifact(path: Path) -> str:
    return str(TypedDigest.from_bytes(DigestKind.ARTIFACT, path.read_bytes()))


def test_check_reconstructs_pristine_seeded_baseline_and_dataset_digests(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/seeded-source",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "public",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout

    pristine_tree = tmp_path / "pristine"
    pristine_tree.mkdir()
    (pristine_tree / "app.txt").write_text("old\n", encoding="utf-8")
    baseline_tree = tmp_path / "baseline"
    baseline_tree.mkdir()
    (baseline_tree / "app.txt").write_text("new\n", encoding="utf-8")
    (baseline_tree / "config").mkdir()
    (baseline_tree / "config/seeded.txt").write_text("asset\n", encoding="utf-8")
    (package / "environment/baseline/app.txt").write_text("new\n", encoding="utf-8")
    (package / "environment/baseline/config").mkdir()
    (package / "environment/baseline/config/seeded.txt").write_text(
        "asset\n",
        encoding="utf-8",
    )
    archive_path = package / "seed/pristine.tar"
    archive_path.parent.mkdir()
    with tarfile.open(archive_path, mode="w") as archive:
        archive.add(pristine_tree / "app.txt", arcname="app.txt")
    patch_path = package / "seed/change.patch"
    patch_path.write_text(
        "diff --git a/app.txt b/app.txt\n"
        "--- a/app.txt\n"
        "+++ b/app.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )
    asset_path = package / "seed/seeded.txt"
    asset_path.write_text("asset\n", encoding="utf-8")
    dataset_path = package / "data/input.csv"
    dataset_path.parent.mkdir()
    dataset_path.write_text("id,value\n1,example\n", encoding="utf-8")

    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["repository"] = {
        "pristine": {
            "origin": "https://github.com/example/source",
            "commit": "a" * 40,
            "archive": "seed/pristine.tar",
            "archive_sha256": _artifact(archive_path),
            "tree_sha256": str(normalized_tree_digest(pristine_tree)),
            "license": "Apache-2.0",
        },
        "seed_inputs": [
            {
                "kind": "git-patch",
                "path": "seed/change.patch",
                "sha256": _artifact(patch_path),
            },
            {
                "destination": "config/seeded.txt",
                "kind": "asset",
                "path": "seed/seeded.txt",
                "sha256": _artifact(asset_path),
            },
        ],
        "baseline_tree_sha256": str(normalized_tree_digest(baseline_tree)),
        "datasets": [
            {
                "id": "example-input",
                "path": "data/input.csv",
                "sha256": _artifact(dataset_path),
                "visibility": "agent",
            }
        ],
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    checked = _run("check", str(package))
    locked = _run("lock", str(package))

    assert checked.returncode == 0, checked.stderr or checked.stdout
    assert locked.returncode == 0, locked.stderr or locked.stdout
    lock = json.loads((package / "scenario.lock.json").read_bytes())
    assert lock["resolved_inputs"]["pristine"]["tree_sha256"] == str(
        normalized_tree_digest(pristine_tree)
    )
    assert lock["resolved_inputs"]["scenario_baseline"] == str(
        normalized_tree_digest(baseline_tree)
    )
    assert lock["resolved_inputs"]["datasets"][0]["sha256"] == _artifact(
        dataset_path
    )


def test_check_rejects_a_non_reproducible_baseline(tmp_path: Path) -> None:
    package = tmp_path / "package"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/non-reproducible",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["repository"]["baseline_tree_sha256"] = (
        "source-tree:sha256:" + "1" * 64
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "source-reconstruction-failed"


def test_seed_asset_cannot_follow_a_symlinked_parent(tmp_path: Path) -> None:
    root = tmp_path / "baseline"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    asset = tmp_path / "asset.txt"
    asset.write_text("secret\n", encoding="utf-8")

    with pytest.raises(ScenarioSourceError, match="cannot apply seed asset"):
        _apply_seed_asset(root, asset, "linked/escaped.txt")

    assert not (outside / "escaped.txt").exists()


@pytest.mark.parametrize(
    "member_name",
    ["../escape", "/escape", "..\\escape", "C:/escape", "./escape", "a//b"],
)
def test_check_rejects_non_portable_or_traversing_archive_members(
    tmp_path: Path,
    member_name: str,
) -> None:
    package = tmp_path / "package"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/unsafe-archive",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    archive_path = package / "seed/pristine.tar"
    archive_path.parent.mkdir()
    with tarfile.open(archive_path, mode="w") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["repository"]["pristine"]["archive"] = "seed/pristine.tar"
    manifest["repository"]["pristine"]["archive_sha256"] = _artifact(archive_path)
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "source-reconstruction-failed"
