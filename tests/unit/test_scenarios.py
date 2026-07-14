from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from model_benchmark.declarations.scenario_locks import _dockerfile_images
from model_benchmark.evidence.capture import CaptureRejected, _read_regular_no_follow


CLI = Path(sys.executable).with_name("model-benchmark")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, "--json", "scenario", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_dockerfile_inventory_includes_every_external_stage_source(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    first = "python:3.12-slim@sha256:" + "1" * 64
    copied = "ghcr.io/example/tool@sha256:" + "2" * 64
    mounted = "docker.io/library/busybox@sha256:" + "3" * 64
    dockerfile.write_text(
        f"FROM --platform=linux/amd64 {first} AS build\n"
        f"COPY --from={copied} \\n  /tool /tool\n"
        f"RUN --mount=type=bind,from={mounted},source=/,target=/helper true\n"
        "FROM build AS final\n",
        encoding="utf-8",
    )

    assert _dockerfile_images(dockerfile) == {first, copied, mounted}


def test_artifact_capture_cannot_follow_a_symlinked_parent(tmp_path: Path) -> None:
    root = tmp_path / "visible"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "result.json").write_text('{"secret":true}\n', encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CaptureRejected) as rejected:
        _read_regular_no_follow(root, root / "linked/result.json", 1024)

    assert rejected.value.code == "artifact_unreadable"


def test_scaffold_creates_one_checkable_standard_v1_package(tmp_path: Path) -> None:
    package = tmp_path / "python-scenario"

    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/python-scenario",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "public",
    )

    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    assert json.loads(scaffold.stdout)["status"] == "candidate"
    assert {path.name for path in package.iterdir()} == {
        "environment",
        "instruction.md",
        "scenario.yaml",
        "solution",
        "task.toml",
        "tests",
    }
    manifest = yaml.safe_load((package / "scenario.yaml").read_text(encoding="utf-8"))
    assert list(manifest) == [
        "schema_version",
        "scenario",
        "repository",
        "instruction",
        "submission",
        "verification",
        "provenance",
    ]
    assert manifest["scenario"]["execution_profile"] == "standard-v1"

    checked = _run("check", str(package))

    assert checked.returncode == 0, checked.stderr or checked.stdout
    summary = json.loads(checked.stdout)
    assert summary["scenario_id"] == "example/python-scenario"
    assert summary["status"] == "candidate-valid"
    assert summary["lock"] == "missing"


def test_check_rejects_unknown_nested_scenario_fields(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/strict-scenario",
        "--ecosystem",
        "angular-typescript",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["scenario"]["unknown"] = True
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    summary = json.loads(checked.stdout)
    assert summary["classification"] == "invalid-scenario-schema"


def test_profile_exception_requires_a_trusted_approval_registry(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/profile-exception",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["scenario"]["execution_profile_exception"] = {
        "approval_reference": "https://github.com/MihaiA24/model-benchmarking/issues/29",
        "approved_by": "ed25519:sha256:" + "1" * 64,
        "deviations": [
            {
                "control": "environment.cpus",
                "value": 4,
            }
        ],
        "id": "integrity-signals-29",
        "stratum": "exception/integrity-signals-29",
        "reason": "exercise the explicit exception boundary",
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    locked = _run("lock", str(package))

    assert locked.returncode != 0
    assert json.loads(locked.stdout)["classification"] == "unsupported-profile-exception"
    assert not (package / "scenario.lock.json").exists()


def test_lock_is_non_circular_byte_reproducible_and_preserves_identities(
    tmp_path: Path,
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/locked-scenario",
        "--ecosystem",
        "spring-boot-java",
        "--visibility",
        "public",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout

    first = _run("lock", str(package))

    assert first.returncode == 0, first.stderr or first.stdout
    lock_path = package / "scenario.lock.json"
    first_bytes = lock_path.read_bytes()
    lock = json.loads(first_bytes)
    assert set(lock["identities"]) == {"scenario", "score_contract", "verifier"}
    assert {identity["kind"] for identity in lock["identities"].values()} == {
        "scenario",
        "score-contract",
        "verifier",
    }
    assert "scenario.lock.json" not in {
        entry["path"] for entry in lock["package"]["files"]
    }

    second = _run("lock", str(package))

    assert second.returncode == 0, second.stderr or second.stdout
    assert lock_path.read_bytes() == first_bytes
    checked = _run("check", str(package))
    assert checked.returncode == 0, checked.stderr or checked.stdout
    assert json.loads(checked.stdout)["lock"] == "valid"


def test_component_identities_change_only_with_their_owned_files(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/component-identities",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    first = _run("lock", str(package))
    assert first.returncode == 0, first.stderr or first.stdout
    original = json.loads((package / "scenario.lock.json").read_bytes())["identities"]

    with (package / "environment/Dockerfile").open("a", encoding="utf-8") as stream:
        stream.write("# runtime identity change\n")
    environment_lock = _run("lock", str(package))
    assert environment_lock.returncode == 0, environment_lock.stderr or environment_lock.stdout
    after_environment = json.loads((package / "scenario.lock.json").read_bytes())[
        "identities"
    ]
    assert after_environment["scenario"] != original["scenario"]
    assert after_environment["verifier"] == original["verifier"]

    with (package / "tests/test.sh").open("a", encoding="utf-8") as stream:
        stream.write("# verifier identity change\n")
    verifier_lock = _run("lock", str(package))
    assert verifier_lock.returncode == 0, verifier_lock.stderr or verifier_lock.stdout
    after_verifier = json.loads((package / "scenario.lock.json").read_bytes())[
        "identities"
    ]
    assert after_verifier["scenario"] == after_environment["scenario"]
    assert after_verifier["verifier"] != after_environment["verifier"]


def test_check_rejects_hidden_marker_bytes_in_agent_visible_inputs(
    tmp_path: Path,
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/leaky-scenario",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    marker = "MODEL_BENCHMARK_HIDDEN:expected-answer\n"
    with (package / "solution/solve.sh").open("a", encoding="utf-8") as stream:
        stream.write(marker)
    (package / "environment/leaked-answer.txt").write_text(marker, encoding="utf-8")

    checked = _run("check", str(package))

    assert checked.returncode != 0
    summary = json.loads(checked.stdout)
    assert summary["classification"] == "answer-leakage"


@pytest.mark.parametrize("hidden", [b"42", b""], ids=["content", "empty"])
def test_check_rejects_copied_hidden_assets_without_markers(
    tmp_path: Path, hidden: bytes
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/copied-hidden-asset",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    (package / "tests/expected.txt").write_bytes(hidden)
    (package / "environment/copied-answer.txt").write_bytes(hidden)

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "answer-leakage"


def test_check_requires_offline_builds_and_authenticated_authors(tmp_path: Path) -> None:
    original = tmp_path / "original"
    scaffold = _run(
        "scaffold",
        str(original),
        "--scenario-id",
        "example/offline-authored",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout

    networked = tmp_path / "networked"
    shutil.copytree(original, networked)
    dockerfile = networked / "environment/Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace("RUN --network=none", "RUN"),
        encoding="utf-8",
    )
    checked = _run("check", str(networked))
    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "download-capable-build"

    anonymous = tmp_path / "anonymous"
    shutil.copytree(original, anonymous)
    manifest_path = anonymous / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["authors"] = []
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    checked = _run("check", str(anonymous))
    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "invalid-scenario-schema"


def test_capture_patch_is_git_compatible_for_edge_cases_and_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/capture-edge-cases",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    capture = package / "environment/capture/capture.py"
    policy = package / "environment/capture/policy.json"
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    output = tmp_path / "capture-output"
    baseline.mkdir()
    candidate.mkdir()
    output.mkdir()
    (baseline / "changed.txt").write_bytes(b"old-without-newline")
    (baseline / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    (candidate / "changed.txt").write_bytes(b"new-without-newline")
    (candidate / "added.txt").write_bytes(b"added-without-newline")

    captured = subprocess.run(
        [
            sys.executable,
            capture,
            "--repository",
            candidate,
            "--baseline",
            baseline,
            "--policy",
            policy,
            "--output",
            output,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert captured.returncode == 0, captured.stderr or captured.stdout
    patch_path = output / "submission.patch"
    patch = patch_path.read_text(encoding="utf-8")
    assert patch.count("\\ No newline at end of file") == 3
    applied = tmp_path / "applied"
    shutil.copytree(baseline, applied)
    checked = subprocess.run(
        ["git", "apply", "--check", patch_path],
        cwd=applied,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr or checked.stdout
    applied_result = subprocess.run(
        ["git", "apply", patch_path],
        cwd=applied,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert applied_result.returncode == 0, applied_result.stderr or applied_result.stdout
    assert (applied / "changed.txt").read_bytes() == b"new-without-newline"
    assert (applied / "added.txt").read_bytes() == b"added-without-newline"
    assert not (applied / "deleted.txt").exists()

    unsafe = tmp_path / "unsafe-candidate"
    shutil.copytree(candidate, unsafe)
    (unsafe / "unsafe name.txt").write_text("unsafe\n", encoding="utf-8")
    unsafe_output = tmp_path / "unsafe-output"
    unsafe_output.mkdir()
    rejected = subprocess.run(
        [
            sys.executable,
            capture,
            "--repository",
            unsafe,
            "--baseline",
            baseline,
            "--policy",
            policy,
            "--output",
            unsafe_output,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert rejected.returncode == 2
    assert json.loads((unsafe_output / "capture.json").read_bytes())["reason"] == "unsafe_path"


def test_capture_policy_limits_only_changed_paths_and_enforces_change_controls(
    tmp_path: Path,
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/changed-path-policy",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    capture = package / "environment/capture/capture.py"

    def invoke(
        name: str,
        baseline: Path,
        candidate: Path,
        policy: dict[str, object],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        policy_path = tmp_path / f"{name}-policy.json"
        output = tmp_path / f"{name}-output"
        output.mkdir()
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                capture,
                "--repository",
                candidate,
                "--baseline",
                baseline,
                "--policy",
                policy_path,
                "--output",
                output,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return completed, json.loads((output / "capture.json").read_bytes())

    baseline = tmp_path / "changed-baseline"
    candidate = tmp_path / "changed-candidate"
    baseline.mkdir()
    candidate.mkdir()
    (baseline / "unchanged.txt").write_text("x" * 4096, encoding="utf-8")
    (candidate / "unchanged.txt").write_text("x" * 4096, encoding="utf-8")
    (baseline / "changed.txt").write_text("old", encoding="utf-8")
    (candidate / "changed.txt").write_text("new", encoding="utf-8")
    policy: dict[str, object] = {
        "allowed_paths": ["changed.txt"],
        "protected_paths": ["protected.txt"],
        "allow_additions": True,
        "allow_deletions": True,
        "forbidden_markers": ["private-canary"],
        "max_file_count": 1,
        "max_total_bytes": 3,
        "stability_window_ms": 1,
    }
    accepted, accepted_record = invoke("changed", baseline, candidate, policy)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert accepted_record["file_count"] == 1
    assert accepted_record["total_bytes"] == 3

    rejected, record = invoke(
        "protected",
        baseline,
        candidate,
        {**policy, "protected_paths": ["changed.txt"]},
    )
    assert rejected.returncode == 2
    assert record["reason"] == "protected_path"

    addition_baseline = tmp_path / "addition-baseline"
    addition_candidate = tmp_path / "addition-candidate"
    addition_baseline.mkdir()
    addition_candidate.mkdir()
    (addition_candidate / "new.txt").write_text("new", encoding="utf-8")
    rejected, record = invoke(
        "addition",
        addition_baseline,
        addition_candidate,
        {**policy, "allowed_paths": ["new.txt"], "allow_additions": False},
    )
    assert rejected.returncode == 2
    assert record["reason"] == "addition_forbidden"

    deletion_baseline = tmp_path / "deletion-baseline"
    deletion_candidate = tmp_path / "deletion-candidate"
    deletion_baseline.mkdir()
    deletion_candidate.mkdir()
    (deletion_baseline / "deleted.txt").write_text("old", encoding="utf-8")
    rejected, record = invoke(
        "deletion",
        deletion_baseline,
        deletion_candidate,
        {**policy, "allowed_paths": ["deleted.txt"], "allow_deletions": False},
    )
    assert rejected.returncode == 2
    assert record["reason"] == "deletion_forbidden"


def test_check_rejects_any_trusted_capture_boundary_drift(tmp_path: Path) -> None:
    original = tmp_path / "original"
    scaffold = _run(
        "scaffold",
        str(original),
        "--scenario-id",
        "example/capture-boundary",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout

    def mutate_compose(package: Path) -> None:
        compose_path = package / "environment/docker-compose.yaml"
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        compose["services"]["capture"]["network_mode"] = "bridge"
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")

    mutations: list[Callable[[Path], object]] = [
        mutate_compose,
        lambda package: (package / "task.toml").write_text(
            (package / "task.toml")
            .read_text(encoding="utf-8")
            .replace("--output /capture", "--output /tmp/capture"),
            encoding="utf-8",
        ),
        lambda package: (package / "environment/capture/Dockerfile").write_text(
            (package / "environment/capture/Dockerfile")
            .read_text(encoding="utf-8")
            .replace("USER 65532:65532", "USER 0:0"),
            encoding="utf-8",
        ),
        lambda package: (package / "environment/capture/capture.py").write_text(
            (package / "environment/capture/capture.py").read_text(encoding="utf-8")
            + "\n# drift\n",
            encoding="utf-8",
        ),
        lambda package: (package / "environment/capture/policy.json").write_text(
            json.dumps(
                {
                    **json.loads(
                        (package / "environment/capture/policy.json").read_text(
                            encoding="utf-8"
                        )
                    ),
                    "allow_additions": False,
                }
            ),
            encoding="utf-8",
        ),
    ]
    for index, mutation in enumerate(mutations):
        package = tmp_path / f"drift-{index}"
        shutil.copytree(original, package)
        mutation(package)
        checked = _run("check", str(package))
        assert checked.returncode != 0
        assert (
            json.loads(checked.stdout)["classification"]
            == "invalid-submission-materialization"
        )


def test_non_patch_output_uses_exact_trusted_materialization(tmp_path: Path) -> None:
    package = tmp_path / "artifact-scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/artifact-output",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root / "schemas/catalog.json").read_text(encoding="utf-8"))
    schema = next(
        entry
        for entry in catalog["schemas"]
        if entry["name"] == "model-benchmark/scenario-review"
    )
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["submission"] = {
        "allowed_paths": ["result.json"],
        "digest_algorithm": "sha256",
        "kind": "artifact",
        "materialization": {
            "destination": "/capture/result.json",
            "mode": "copy-no-follow",
            "service": "capture",
        },
        "max_bytes": 1024,
        "media_type": "application/json",
        "schema": {
            "name": schema["name"],
            "sha256": schema["sha256"],
            "version": schema["version"],
        },
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    command = (
        "python3 /opt/capture/capture.py --artifact-source /input/repository/result.json "
        "--artifact-output /capture/result.json "
        "--artifact-record /capture/materialization.json "
        "--artifact-media-type application/json "
        f"--artifact-schema-sha256 {schema['sha256']} --artifact-max-bytes 1024 "
        "--visibility-root /input/repository --forbidden-marker "
        "MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary "
        "--stability-window-ms 250"
    )
    task_path = package / "task.toml"
    task = task_path.read_text(encoding="utf-8")
    artifacts_start = task.index("artifacts = [")
    artifacts_end = task.index("\n\n[task]", artifacts_start)
    task = (
        task[:artifacts_start]
        + "artifacts = [\n"
        + '  { source = "/capture/materialization.json", service = "capture" },\n'
        + '  { source = "/capture/result.json", service = "capture" },\n'
        + "]"
        + task[artifacts_end:]
    )
    collect_start = task.index("[[verifier.collect]]")
    collect_end = task.index("\n[agent]", collect_start)
    task = (
        task[:collect_start]
        + "[[verifier.collect]]\n"
        + 'service = "capture"\n'
        + f'command = "{command}"\n'
        + "timeout_sec = 30.0\n"
        + task[collect_end:]
    )
    task_path.write_text(task, encoding="utf-8")

    checked = _run("check", str(package))
    assert checked.returncode == 0, checked.stderr or checked.stdout

    repository = tmp_path / "artifact-repository"
    capture_output = tmp_path / "artifact-capture"
    repository.mkdir()
    capture_output.mkdir()
    (repository / "result.json").write_text('{"result":"ok"}\n', encoding="utf-8")
    captured = subprocess.run(
        [
            sys.executable,
            package / "environment/capture/capture.py",
            "--artifact-source",
            repository / "result.json",
            "--artifact-output",
            capture_output / "result.json",
            "--artifact-record",
            capture_output / "materialization.json",
            "--artifact-media-type",
            "application/json",
            "--artifact-schema-sha256",
            schema["sha256"],
            "--artifact-max-bytes",
            "1024",
            "--visibility-root",
            repository,
            "--forbidden-marker",
            "MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary",
            "--stability-window-ms",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert captured.returncode == 0, captured.stderr or captured.stdout
    materialization = json.loads((capture_output / "materialization.json").read_bytes())
    assert materialization["status"] == "accepted"
    assert materialization["artifact_sha256"] == hashlib.sha256(
        (capture_output / "result.json").read_bytes()
    ).hexdigest()
    assert materialization["hidden_markers"]["status"] == "absent"

    drifted = tmp_path / "artifact-drifted"
    shutil.copytree(package, drifted)
    drifted_task = drifted / "task.toml"
    drifted_task.write_text(
        drifted_task.read_text(encoding="utf-8").replace(
            "--artifact-max-bytes 1024",
            "--artifact-max-bytes 2048",
        ),
        encoding="utf-8",
    )
    rejected = _run("check", str(drifted))
    assert rejected.returncode != 0
    assert json.loads(rejected.stdout)["classification"] == "invalid-submission-materialization"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace(
            "schema_version: 1\n",
            "schema_version: 1\nschema_version: 1\n",
            1,
        ),
        lambda text: text.replace("schema_version: 1", "schema_version: &version 1", 1),
    ],
    ids=["duplicate-key", "anchor"],
)
def test_check_rejects_ambiguous_yaml(
    tmp_path: Path,
    mutation: Callable[[str], str],
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/strict-yaml",
        "--ecosystem",
        "angular-typescript",
        "--visibility",
        "public",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    manifest_path = package / "scenario.yaml"
    manifest_path.write_text(
        mutation(manifest_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "invalid-scenario-yaml"


def test_check_rejects_unknown_harbor_fields_and_profile_drift(tmp_path: Path) -> None:
    unknown_package = tmp_path / "unknown-task-field"
    drifted_package = tmp_path / "drifted-profile"
    for package, identifier in (
        (unknown_package, "unknown-task-field"),
        (drifted_package, "drifted-profile"),
    ):
        scaffold = _run(
            "scaffold",
            str(package),
            "--scenario-id",
            f"example/{identifier}",
            "--ecosystem",
            "spring-boot-java",
            "--visibility",
            "private",
        )
        assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    with (unknown_package / "task.toml").open("a", encoding="utf-8") as stream:
        stream.write("unknown_policy = true\n")
    drifted_task = (drifted_package / "task.toml").read_text(encoding="utf-8")
    (drifted_package / "task.toml").write_text(
        drifted_task.replace("memory_mb = 512", "memory_mb = 1024"),
        encoding="utf-8",
    )

    unknown = _run("check", str(unknown_package))
    drifted = _run("check", str(drifted_package))

    assert json.loads(unknown.stdout)["classification"] == "invalid-harbor-task"
    assert json.loads(drifted.stdout)["classification"] == "profile-mismatch"


def test_check_rejects_a_harbor_task_name_that_differs_from_scenario_id(
    tmp_path: Path,
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/cross-file-identity",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    task_path = package / "task.toml"
    task_path.write_text(
        task_path.read_text(encoding="utf-8").replace(
            'name = "example/cross-file-identity"',
            'name = "example/different-task"',
        ),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "invalid-harbor-task"


@pytest.mark.parametrize("input_kind", ["archive", "seed", "dataset"])
def test_declared_inputs_cannot_escape_their_canonical_roots(
    tmp_path: Path,
    input_kind: str,
) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        f"example/{input_kind}-root",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    escaped = package / "environment/Dockerfile"
    digest = "artifact:sha256:" + hashlib.sha256(escaped.read_bytes()).hexdigest()
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if input_kind == "archive":
        manifest["repository"]["pristine"]["archive"] = "environment/Dockerfile"
        manifest["repository"]["pristine"]["archive_sha256"] = digest
    elif input_kind == "seed":
        manifest["repository"]["seed_inputs"] = [
            {
                "kind": "git-patch",
                "path": "environment/Dockerfile",
                "sha256": digest,
            }
        ]
    else:
        manifest["repository"]["datasets"] = [
            {
                "id": "escaped",
                "path": "environment/Dockerfile",
                "sha256": digest,
                "visibility": "agent",
            }
        ]
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "invalid-scenario-schema"


def test_non_patch_output_schema_must_resolve_from_the_catalog(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/unresolved-output-schema",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["submission"] = {
        "allowed_paths": ["submission/output.json"],
        "digest_algorithm": "sha256",
        "kind": "artifact",
        "materialization": {
            "destination": "/capture/output.json",
            "mode": "copy-no-follow",
            "service": "capture",
        },
        "max_bytes": 1000,
        "media_type": "application/json",
        "schema": {
            "name": "example/missing-output",
            "sha256": "schema:sha256:" + "0" * 64,
            "version": 1,
        },
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    checked = _run("check", str(package))

    assert checked.returncode != 0
    assert json.loads(checked.stdout)["classification"] == "invalid-scenario-schema"


def test_failed_relock_removes_the_previous_authoritative_lock(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/stale-lock-cleanup",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    locked = _run("lock", str(package))
    assert locked.returncode == 0, locked.stderr or locked.stdout
    lock_path = package / "scenario.lock.json"
    assert lock_path.is_file()
    with (package / "instruction.md").open("a", encoding="utf-8") as stream:
        stream.write("mutation after lock\n")

    relocked = _run("lock", str(package))

    assert relocked.returncode != 0
    assert not lock_path.exists()


def test_lock_binds_canonical_file_modes(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/canonical-mode",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    first = _run("lock", str(package))
    assert first.returncode == 0, first.stderr or first.stdout
    (package / "task.toml").chmod(0o755)

    stale = _run("check", str(package))

    assert stale.returncode != 0
    assert json.loads(stale.stdout)["classification"] == "stale-package-lock"
    relocked = _run("lock", str(package))
    assert relocked.returncode == 0, relocked.stderr or relocked.stdout
    lock = json.loads((package / "scenario.lock.json").read_bytes())
    task = next(
        entry for entry in lock["package"]["files"] if entry["path"] == "task.toml"
    )
    assert task["mode"] == "0755"


def test_domain_scores_map_each_domain_group_exactly_once(tmp_path: Path) -> None:
    package = tmp_path / "scenario"
    scaffold = _run(
        "scaffold",
        str(package),
        "--scenario-id",
        "example/domain-scores",
        "--ecosystem",
        "python-data-engineering",
        "--visibility",
        "private",
    )
    assert scaffold.returncode == 0, scaffold.stderr or scaffold.stdout
    manifest_path = package / "scenario.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["verification"]["check_groups"].append(
        {
            "class": "domain",
            "evidence_key": "domain",
            "id": "domain",
            "required": False,
            "score_direction": "maximize",
            "weight": "1",
        }
    )
    manifest["verification"]["domain_scores"] = [
        {"check_groups": ["domain"], "name": "correctness_score"}
    ]
    for field, value in (
        ("baseline_score_vector", "0"),
        ("reference_score_vector", "1"),
    ):
        manifest["verification"]["qualification"][field].append(
            {"name": "correctness_score", "value": value}
        )
        manifest["verification"]["qualification"][field].sort(
            key=lambda entry: entry["name"]
        )
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    locked = _run("lock", str(package))

    assert locked.returncode == 0, locked.stderr or locked.stdout
    (package / "scenario.lock.json").unlink()
    manifest["verification"]["domain_scores"].append(
        {"check_groups": ["domain"], "name": "performance_score"}
    )
    for field in ("baseline_score_vector", "reference_score_vector"):
        manifest["verification"]["qualification"][field].append(
            {"name": "performance_score", "value": "0"}
        )
        manifest["verification"]["qualification"][field].sort(
            key=lambda entry: entry["name"]
        )
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    rejected = _run("check", str(package))

    assert rejected.returncode != 0
    assert "uniquely and completely map" in json.loads(rejected.stdout)["message"]
