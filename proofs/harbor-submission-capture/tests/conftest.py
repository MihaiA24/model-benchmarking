from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest


PROOF_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = PROOF_ROOT / "artifacts"
CASE_ROOT = ARTIFACT_ROOT / "cases"
CANONICAL_COMMAND = (
    "uv run --project proofs/harbor-submission-capture --frozen pytest -q "
    "proofs/harbor-submission-capture/tests --maxfail=1"
)
HARBOR_COMMIT = "527d50deb63a5d279e8c20593c18a2cbc7f61f9e"
HARBOR_SOURCE = (
    "https://github.com/harbor-framework/harbor.git?rev="
    f"{HARBOR_COMMIT}#{HARBOR_COMMIT}"
)
BASE_IMAGE = (
    "python:3.12.12-slim-bookworm@"
    "sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
)
CASE_DISPOSITIONS = {
    "normal-patch": "accepted normalized patch",
    "no-op": "accepted explicit no-op",
    "malicious-path": "rejected undeclared path",
    "symlink": "rejected symlink",
    "special-file": "rejected special file",
    "oversized": "rejected byte limit",
    "racing-descendant": "accepted stable post-stop patch",
    "missing-capture": "rejected missing capture",
}
CASE_ASSERTIONS = {
    "normal-patch": [
        "main stopped before capture hook",
        "separate verifier received only capture.json and submission.patch",
        "agent-home marker absent from normalized patch",
    ],
    "no-op": [
        "main stopped before capture hook",
        "empty patch represented as explicit accepted no-op",
    ],
    "malicious-path": ["undeclared path rejected", "no patch artifact collected"],
    "symlink": ["symlink rejected without dereference", "no patch artifact collected"],
    "special-file": ["special file rejected", "no patch artifact collected"],
    "oversized": ["byte limit enforced", "no patch artifact collected"],
    "racing-descendant": [
        "main and descendant stopped before capture hook",
        "repository stable across capture window",
    ],
    "missing-capture": [
        "both declared capture artifacts missing",
        "separate verifier reward remained zero",
    ],
}

_CASE_RESULTS: dict[str, dict[str, str]] = {}
_REQUESTED_FULL_PROOF_SUITE = False
_FULL_PROOF_SUITE = False
_ANY_SKIP = False


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _case_for_item(item: pytest.Item) -> str | None:
    original_name = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
    if original_name == "test_normal_patch_uses_post_stop_sidecar_and_separate_verifier":
        return "normal-patch"
    if original_name == "test_noop_is_an_explicit_accepted_submission":
        return "no-op"
    if original_name == "test_racing_descendant_is_stopped_before_stable_capture":
        return "racing-descendant"
    if original_name == "test_missing_capture_never_becomes_an_authoritative_submission":
        return "missing-capture"
    if original_name == "test_unsafe_repository_state_is_rejected_without_partial_submission":
        callspec = getattr(item, "callspec", None)
        if callspec is not None:
            return str(callspec.params["name"])
    return None


def _remove_authoritative_outputs() -> None:
    for path in CASE_ROOT.glob("*.json") if CASE_ROOT.exists() else ():
        path.unlink()
    for name in ("proof-report.json", "sha256sums.txt"):
        (ARTIFACT_ROOT / name).unlink(missing_ok=True)


def _atomic_verified_write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    readback = path.read_bytes()
    if readback != data:
        raise RuntimeError(f"read-back mismatch for {path}")
    digest = _sha256(data)
    if _sha256(readback) != digest:
        raise RuntimeError(f"SHA-256 read-back mismatch for {path}")
    return digest


def _is_canonical_full_invocation(config: pytest.Config) -> bool:
    targets = [Path(argument).resolve() for argument in config.args]
    return (
        config.getoption("maxfail") == 1
        and targets == [(PROOF_ROOT / "tests").resolve()]
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    global _REQUESTED_FULL_PROOF_SUITE
    _REQUESTED_FULL_PROOF_SUITE = _is_canonical_full_invocation(session.config)
    if _REQUESTED_FULL_PROOF_SUITE:
        _remove_authoritative_outputs()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    global _FULL_PROOF_SUITE
    collected_cases = {_case_for_item(item) for item in items}
    collected_cases.discard(None)
    _FULL_PROOF_SUITE = collected_cases == set(CASE_DISPOSITIONS)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    global _ANY_SKIP
    outcome = yield
    report = outcome.get_result()
    if report.skipped:
        _ANY_SKIP = True
    if report.when != "call":
        return
    case = _case_for_item(item)
    if case is not None:
        _CASE_RESULTS[case] = {
            "nodeid": item.nodeid,
            "outcome": report.outcome,
        }


def _publish_authoritative_outputs() -> None:
    outputs: list[dict[str, str]] = []
    for case in sorted(CASE_DISPOSITIONS):
        payload = {
            "assertions": CASE_ASSERTIONS[case],
            "case": case,
            "disposition": CASE_DISPOSITIONS[case],
            "result": "passed",
            "test_nodeid": _CASE_RESULTS[case]["nodeid"],
        }
        relative = Path("artifacts") / "cases" / f"{case}.json"
        digest = _atomic_verified_write(PROOF_ROOT / relative, _canonical_json(payload))
        outputs.append({"path": relative.as_posix(), "sha256": digest})

    report = {
        "cases": [
            {
                "case": case,
                "disposition": CASE_DISPOSITIONS[case],
                "result": "passed",
            }
            for case in sorted(CASE_DISPOSITIONS)
        ],
        "checksum_manifest": "artifacts/sha256sums.txt",
        "command": CANONICAL_COMMAND,
        "inputs": {
            "base_image": BASE_IMAGE,
            "fixture_tree_sha256": _tree_sha256(PROOF_ROOT / "fixtures"),
            "harbor_commit": HARBOR_COMMIT,
            "harbor_lock_source": HARBOR_SOURCE,
            "pyproject_sha256": _sha256((PROOF_ROOT / "pyproject.toml").read_bytes()),
            "tests_tree_sha256": _tree_sha256(PROOF_ROOT / "tests"),
            "uv_lock_sha256": _sha256((PROOF_ROOT / "uv.lock").read_bytes()),
        },
        "outputs": outputs,
        "schema_version": "harbor-submission-capture-proof-v1",
    }
    report_path = ARTIFACT_ROOT / "proof-report.json"
    report_digest = _atomic_verified_write(report_path, _canonical_json(report))

    checksummed = outputs + [
        {"path": "artifacts/proof-report.json", "sha256": report_digest}
    ]
    checksum_bytes = "".join(
        f"{entry['sha256']}  {entry['path']}\n"
        for entry in sorted(checksummed, key=lambda entry: entry["path"])
    ).encode()
    checksum_path = ARTIFACT_ROOT / "sha256sums.txt"
    _atomic_verified_write(checksum_path, checksum_bytes)

    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected_digest, relative_path = line.split("  ", 1)
        actual_digest = _sha256((PROOF_ROOT / relative_path).read_bytes())
        if actual_digest != expected_digest:
            raise RuntimeError(f"checksum verification failed for {relative_path}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _REQUESTED_FULL_PROOF_SUITE:
        return
    if (
        not _FULL_PROOF_SUITE
        or exitstatus != pytest.ExitCode.OK
        or _ANY_SKIP
        or set(_CASE_RESULTS) != set(CASE_DISPOSITIONS)
        or any(result["outcome"] != "passed" for result in _CASE_RESULTS.values())
    ):
        _remove_authoritative_outputs()
        if exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return

    try:
        _publish_authoritative_outputs()
    except BaseException:
        _remove_authoritative_outputs()
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        raise
