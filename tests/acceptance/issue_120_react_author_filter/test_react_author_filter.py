from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from model_benchmark.declarations.functional_v1 import CONDITIONS, FunctionalV1Manifest, SCENARIOS
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "scenarios/calibration/react-author-filter"
EVIDENCE = ROOT / "artifacts/qualification/functional-v1/react-author-filter.json"
REGISTRY = SchemaRegistry(schema_root_path())


def run_scenario(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["model-benchmark-scenario", "--json", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


REFERENCE_INSERTION = """    case 'FILTER_BY_AUTHOR':
      return {
        ...state,
        articles: state.articles.filter(
          article => article.author.username === action.author
        ),
        filteredByAuthor: action.author
      };
"""
BRANCH_ACTIONS = (
    ("article-favorited", "ARTICLE_FAVORITED"),
    ("article-unfavorited", "ARTICLE_UNFAVORITED"),
    ("set-page", "SET_PAGE"),
    ("apply-tag-filter", "APPLY_TAG_FILTER"),
    ("home-page-loaded", "HOME_PAGE_LOADED"),
    ("home-page-unloaded", "HOME_PAGE_UNLOADED"),
    ("change-tab", "CHANGE_TAB"),
    ("profile-page-loaded", "PROFILE_PAGE_LOADED"),
    ("profile-favorites-page-loaded", "PROFILE_FAVORITES_PAGE_LOADED"),
    ("profile-page-unloaded", "PROFILE_PAGE_UNLOADED"),
    ("profile-favorites-page-unloaded", "PROFILE_FAVORITES_PAGE_UNLOADED"),
)


def reference_source() -> tuple[str, str]:
    baseline = (
        PACKAGE / "environment/baseline/src/reducers/articleList.js"
    ).read_text(encoding="utf-8")
    needle = "    case SET_PAGE:\n"
    assert baseline.count(needle) == 1
    return baseline, baseline.replace(needle, REFERENCE_INSERTION + needle)


def faulty_submissions() -> list[tuple[str, str, dict[str, int]]]:
    _, reference = reference_source()
    zero_match = reference.replace(
        "        filteredByAuthor: action.author\n",
        """        filteredByAuthor: state.articles.some(
          article => article.author.username === action.author
        ) ? action.author : state.filteredByAuthor
""",
        1,
    )
    mutating = reference.replace(
        REFERENCE_INSERTION,
        """    case 'FILTER_BY_AUTHOR':
      state.articles = state.articles.filter(
        article => article.author.username === action.author
      );
      state.filteredByAuthor = action.author;
      return state;
""",
        1,
    )
    faults = [
        (
            "zero-match-marker",
            zero_match,
            {
                "acceptance_score": 0,
                "author_filter_state": 1,
                "regression_score": 1,
                "task_success": 0,
            },
        ),
        (
            "input-mutation",
            mutating,
            {
                "acceptance_score": 0,
                "author_filter_state": 0,
                "regression_score": 1,
                "task_success": 0,
            },
        ),
    ]
    reducer_start = "export default (state = {}, action) => {\n"
    for identifier, action_type in BRANCH_ACTIONS:
        faulty = reference.replace(
            reducer_start,
            reducer_start + f"  if (action.type === '{action_type}') return state;\n",
            1,
        )
        faults.append(
            (
                identifier,
                faulty,
                {
                    "acceptance_score": 1,
                    "author_filter_state": 1,
                    "regression_score": 0,
                    "task_success": 0,
                },
            )
        )
    default_fault = reference.replace(
        reducer_start,
        reducer_start
        + "  if (action.type === 'UNRELATED_ACTION') return { ...state };\n",
        1,
    )
    faults.append(
        (
            "default",
            default_fault,
            {
                "acceptance_score": 1,
                "author_filter_state": 1,
                "regression_score": 0,
                "task_success": 0,
            },
        )
    )
    isolation_fault = "import fs from 'node:fs';\nfs.readFileSync('/tests/verify.mjs');\n" + reference
    faults.append(
        (
            "verifier-file-read",
            isolation_fault,
            {
                "acceptance_score": 0,
                "author_filter_state": 0,
                "regression_score": 0,
                "task_success": 0,
            },
        )
    )
    return faults


def run_isolated_verifier(
    tmp_path: Path,
    identifier: str,
    submitted_source: str,
) -> dict[str, int]:
    baseline, _ = reference_source()
    run_root = tmp_path / identifier
    capture = run_root / "capture"
    verifier_logs = run_root / "logs/verifier"
    capture.mkdir(parents=True)
    verifier_logs.mkdir(parents=True)
    os.chmod(verifier_logs, 0o777)
    patch = "".join(
        difflib.unified_diff(
            baseline.splitlines(keepends=True),
            submitted_source.splitlines(keepends=True),
            fromfile="a/src/reducers/articleList.js",
            tofile="b/src/reducers/articleList.js",
        )
    )
    (capture / "submission.patch").write_text(patch, encoding="utf-8")
    override = run_root / "compose.override.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "main": {
                        "command": ["/tests/test.sh"],
                        "working_dir": "/workspace/repository",
                        "volumes": [
                            f"{capture}:/capture:ro",
                            f"{run_root / 'logs'}:/logs",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    compose = PACKAGE / "tests/docker-compose.yaml"
    project = "react-verifier-" + hashlib.sha256(str(run_root).encode()).hexdigest()[:12]
    base_command = [
        "docker",
        "compose",
        "--progress",
        "quiet",
        "-p",
        project,
        "-f",
        str(compose),
        "-f",
        str(override),
    ]
    try:
        completed = subprocess.run(
            [
                *base_command,
                "up",
                "--build",
                "--abort-on-container-exit",
                "--exit-code-from",
                "main",
            ],
            cwd=PACKAGE / "tests",
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        return json.loads((verifier_logs / "reward.json").read_text(encoding="utf-8"))
    finally:
        subprocess.run(
            [*base_command, "down", "-v", "--remove-orphans"],
            cwd=PACKAGE / "tests",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


def test_react_package_is_public_bounded_and_reproducible(tmp_path: Path) -> None:
    manifest = yaml.safe_load((PACKAGE / "scenario.yaml").read_text(encoding="utf-8"))
    assert manifest["scenario"] == {
        "id": "functional-v1/react-author-filter",
        "version": "1.0.0",
        "lifecycle_state": "candidate",
        "visibility": "public",
        "ecosystem": "react-javascript",
        "workload_family": "bounded-feature-implementation",
        "difficulty": "standard",
        "execution_profile": "standard-v1",
    }
    assert manifest["repository"]["pristine"] == {
        **manifest["repository"]["pristine"],
        "origin": "https://github.com/gothinkster/react-redux-realworld-example-app",
        "commit": "ee72eba4056392c95a27bc48d385d3f54ba38a18",
        "license": "MIT",
    }
    assert manifest["repository"]["seed_inputs"] == []
    assert manifest["submission"] == {
        "kind": "git-patch",
        "repository_root": "/workspace/repository",
        "allowed_paths": ["src/reducers/articleList.js"],
        "protected_paths": [".git/**"],
        "allow_additions": False,
        "allow_deletions": False,
        "max_files": 1,
        "max_bytes": 50_000,
        "symlinks": "reject",
        "executable_bits": "reject",
        "submodules": "reject",
        "nested_repositories": "reject",
        "binary_files": "reject",
    }
    assert [
        (group["id"], group["class"], group["required"])
        for group in manifest["verification"]["check_groups"]
    ] == [
        ("author-filter-output", "acceptance", True),
        ("author-filter-state", "domain", True),
        ("reducer-regression", "regression", True),
    ]
    assert any(
        "does not claim byte-identical legacy provenance" in disclosure
        for disclosure in manifest["provenance"]["contamination_disclosures"]
    )

    checked = run_scenario("check", str(PACKAGE))
    assert checked.returncode == 0, checked.stderr or checked.stdout
    assert json.loads(checked.stdout)["lock"] == "valid"

    copied = tmp_path / PACKAGE.name
    shutil.copytree(PACKAGE, copied)
    expected_lock = (copied / "scenario.lock.json").read_bytes()
    relocked = run_scenario("lock", str(copied))
    assert relocked.returncode == 0, relocked.stderr or relocked.stdout
    assert (copied / "scenario.lock.json").read_bytes() == expected_lock


def test_offline_dependency_closure_is_exact_and_content_addressed() -> None:
    dependencies = PACKAGE / "environment/dependencies"
    package = json.loads((dependencies / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((dependencies / "package-lock.json").read_text(encoding="utf-8"))
    assert package["packageManager"] == "npm@10.9.2"
    assert package["engines"] == {"node": "22.17.0"}
    requested = package["dependencies"] | package["devDependencies"]
    assert requested
    assert all(not set(version) & set("^~*<>=| " ) for version in requested.values())
    assert lock["lockfileVersion"] == 3
    assert len(lock["packages"]) >= 1400
    for name, version in requested.items():
        assert lock["packages"][f"node_modules/{name}"]["version"] == version
    unlocked = [
        path
        for path, entry in lock["packages"].items()
        if path and not entry.get("link") and not entry.get("integrity")
    ]
    assert unlocked == []
    archive = dependencies / "node_modules.tar.gz"
    expected_digest, expected_name = (
        dependencies / "node_modules.tar.gz.sha256"
    ).read_text(encoding="utf-8").split()
    with archive.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected_digest
    assert expected_name == "node_modules.tar.gz"


def test_evaluator_has_only_bounded_named_volume_exchange() -> None:
    compose = yaml.safe_load((PACKAGE / "tests/docker-compose.yaml").read_text(encoding="utf-8"))
    main = compose["services"]["main"]
    evaluator = compose["services"]["evaluator"]
    assert main["network_mode"] == "none"
    assert main["cap_drop"] == ["ALL"]
    assert main["cap_add"] == ["CHOWN"]
    assert main["depends_on"] == {"evaluator": {"condition": "service_started"}}
    assert "depends_on" not in evaluator
    assert evaluator["network_mode"] == "none"
    assert evaluator["read_only"] is True
    assert evaluator["cap_drop"] == ["ALL"]
    assert evaluator["security_opt"] == ["no-new-privileges:true"]
    assert evaluator["user"] == "65532:65532"
    assert set(evaluator["volumes"]) == {
        "evaluator-repository:/repository:ro",
        "evaluator-request:/request:ro",
        "evaluator-result:/result",
    }
    expected_sizes = {
        "evaluator-repository": "64m",
        "evaluator-request": "1m",
        "evaluator-result": "1m",
    }
    assert set(compose["volumes"]) == set(expected_sizes)
    for name, size in expected_sizes.items():
        assert compose["volumes"][name] == {
            "driver": "local",
            "driver_opts": {
                "device": "tmpfs",
                "o": f"size={size},uid=65532,gid=65532,mode=0700",
                "type": "tmpfs",
            },
        }
    evaluator_contract = json.dumps(evaluator, sort_keys=True)
    for forbidden in ("/tests", "/logs", "/capture", "docker.sock", "environment"):
        assert forbidden not in evaluator_contract


def test_evaluator_rejects_command_and_path_requests(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    request = tmp_path / "request"
    result = tmp_path / "result"
    output = tmp_path / "output"
    shutil.copytree(PACKAGE / "environment/baseline", repository)
    for directory in (request, result, output):
        directory.mkdir()
        os.chmod(directory, 0o777)
    (request / "request.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "operation": "evaluate-functional-v1-react-author-filter",
                "command": "node",
                "path": "/tests/verify.mjs",
                "cases": [
                    {
                        "id": "arbitrary-request",
                        "state": {},
                        "action": {"type": "UNRELATED_ACTION"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    override = tmp_path / "compose.override.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "main": {
                        "command": [
                            "sh",
                            "-c",
                            "while [ ! -f /evaluator-result/result.json ]; do sleep 0.05; done; "
                            "cat /evaluator-result/result.json > /output/result.json",
                        ],
                        "volumes": [
                            f"{result}:/evaluator-result",
                            f"{output}:/output",
                        ],
                    },
                    "evaluator": {
                        "volumes": [
                            f"{repository}:/repository:ro",
                            f"{request}:/request:ro",
                            f"{result}:/result",
                        ]
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    compose = PACKAGE / "tests/docker-compose.yaml"
    project = "react-request-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    base_command = [
        "docker",
        "compose",
        "--progress",
        "quiet",
        "-p",
        project,
        "-f",
        str(compose),
        "-f",
        str(override),
    ]
    try:
        completed = subprocess.run(
            [
                *base_command,
                "up",
                "--build",
                "--abort-on-container-exit",
                "--exit-code-from",
                "main",
            ],
            cwd=PACKAGE / "tests",
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    finally:
        subprocess.run(
            [*base_command, "down", "-v", "--remove-orphans"],
            cwd=PACKAGE / "tests",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    assert json.loads((output / "result.json").read_text(encoding="utf-8")) == {
        "cases": [],
        "errorCode": "invalid-request",
        "evaluatorStatus": "error",
        "operation": "evaluate-functional-v1-react-author-filter",
        "schemaVersion": 1,
    }


FAULTY_SUBMISSIONS = faulty_submissions()


@pytest.mark.parametrize(
    ("identifier", "submitted_source", "expected_scores"),
    FAULTY_SUBMISSIONS,
    ids=[record[0] for record in FAULTY_SUBMISSIONS],
)
def test_each_plausible_fault_is_rejected(
    tmp_path: Path,
    identifier: str,
    submitted_source: str,
    expected_scores: dict[str, int],
) -> None:
    assert run_isolated_verifier(tmp_path, identifier, submitted_source) == expected_scores


def test_reference_submission_passes_isolated_matrix(tmp_path: Path) -> None:
    _, reference = reference_source()
    assert run_isolated_verifier(tmp_path, "reference", reference) == {
        "acceptance_score": 1,
        "author_filter_state": 1,
        "regression_score": 1,
        "task_success": 1,
    }


def test_qualification_proves_behavior_and_isolation() -> None:
    manifest = yaml.safe_load((PACKAGE / "scenario.yaml").read_text(encoding="utf-8"))
    lock = REGISTRY.validate_bytes((PACKAGE / "scenario.lock.json").read_bytes())
    evidence_bytes = EVIDENCE.read_bytes()
    technical = REGISTRY.validate_bytes(evidence_bytes)
    runs = technical["runs"]
    declared = manifest["verification"]["qualification"]

    assert technical["candidate_status"] == "technically-qualified"
    assert technical["package_payload_sha256"] == lock["package"]["payload_sha256"]
    assert runs["baseline"]["outcome"] == "declared-failure"
    assert runs["baseline"]["structured_score_vector"] == declared["baseline_score_vector"]
    assert runs["baseline"]["reward_score_vector"] == declared["baseline_score_vector"]
    assert [record["outcome"] for record in runs["reference"]] == ["passed", "passed"]
    for record in runs["reference"]:
        assert record["structured_score_vector"] == declared["reference_score_vector"]
        assert record["reward_score_vector"] == declared["reference_score_vector"]
    assert runs["hidden_marker"]["status"] == "passed"
    assert [record["kind"] for record in runs["handoffs"]] == ["malformed", "unsafe"]
    assert all(record["task_success"] is False for record in runs["handoffs"])
    assert runs["score_mismatch"]["status"] == "passed"
    assert runs["no_download"] is True
    assert b"MODEL_BENCHMARK_HIDDEN" not in evidence_bytes
    assert b"MODEL_BENCHMARK_PROVIDER_API_KEY" not in evidence_bytes


def test_react_package_activates_as_fourth_functional_v1_scenario() -> None:
    assert SCENARIOS == (
        "python-sales-by-genre",
        "spring-petvalidator-whitespace",
        "angular-reading-time",
        "react-author-filter",
    )
    assert len(SCENARIOS) * len(CONDITIONS) == 16
    manifests = sorted(ROOT.glob("functional-v1*.yaml"))
    assert len(manifests) == 4
    for path in manifests:
        loaded = FunctionalV1Manifest.load(path)
        assert tuple(loaded.scenario_locks) == SCENARIOS
        assert loaded.identity_value["scenarios"]["react-author-filter"]["digest"] == (
            "package-lock:sha256:89626643a38dd734b3cb52b03a98ee0c70db59dc3e43870c6d2ee4bb80cedd4f"
        )
