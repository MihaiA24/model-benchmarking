from __future__ import annotations

from pathlib import Path

import pytest

from model_benchmark.declarations.functional_v1 import FunctionalV1Manifest
from model_benchmark.runtime.functional_v1 import FunctionalV1Home, FunctionalV1HomeError


def test_resume_lookup_revalidates_write_once_input_identities(
    manifest_bundle: tuple[Path, dict[str, object]],
    tmp_path: Path,
) -> None:
    manifest = FunctionalV1Manifest.load(manifest_bundle[0])
    home = FunctionalV1Home(tmp_path / "home")
    workspace = home.create_workspace(manifest)
    source = workspace.root / "input/source.yaml"
    source.chmod(0o600)
    source.write_bytes(source.read_bytes() + b"# tampered\n")

    with pytest.raises(FunctionalV1HomeError) as captured:
        home.workspace(workspace.run_id)

    assert captured.value.reason_code == "corrupt-run-workspace"
