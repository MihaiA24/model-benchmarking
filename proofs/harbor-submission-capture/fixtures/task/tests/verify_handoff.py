#!/usr/bin/env python3
"""Verifier-side proof that only the accepted handoff crossed environments."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


EXPECTED_PATCH = """diff --git a/src/app.txt b/src/app.txt
--- a/src/app.txt
+++ b/src/app.txt
@@ -1 +1 @@
-before
+after
diff --git a/src/new.txt b/src/new.txt
new file mode 100644
--- /dev/null
+++ b/src/new.txt
@@ -0,0 +1 @@
+new
"""
REWARD_PATH = Path("/logs/verifier/reward.txt")


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    REWARD_PATH.write_text("0", encoding="utf-8")
    return 1


def main() -> int:
    try:
        expected = json.loads(Path("/tests/expected.json").read_text(encoding="utf-8"))
        capture_dir = Path("/capture")
        names = sorted(path.name for path in capture_dir.iterdir())
        assert names == ["capture.json", "submission.patch"], names
        record = json.loads((capture_dir / "capture.json").read_text(encoding="utf-8"))
        patch = (capture_dir / "submission.patch").read_bytes()

        assert record["status"] == expected["status"] == "accepted"
        assert record["kind"] == expected["kind"]
        assert record["schema_version"] == "proof-capture-v1"
        assert record["stability_window_ms"] == 250
        assert record["patch_sha256"] == hashlib.sha256(patch).hexdigest()
        if expected["case"] == "normal-patch":
            assert record["kind"] == "patch"
            assert patch.decode("utf-8") == EXPECTED_PATCH
        elif expected["case"] == "no-op":
            assert record["kind"] == "no-op"
            assert patch == b""
        elif expected["case"] == "racing-descendant":
            assert record["kind"] == "patch"
            assert b"src/race.txt" in patch
            assert b"src/descendant.pid" in patch
            assert record["total_bytes"] <= 1024
        else:
            raise AssertionError(f"unexpected accepted case: {expected['case']}")
        assert len(record["baseline_sha256"]) == 64
        assert len(record["final_sha256"]) == 64
        assert len(record["collector"]["capture_source_sha256"]) == 64
        assert len(record["collector"]["policy_sha256"]) == 64

        assert not Path("/workspace/repo/src/app.txt").exists()
        assert not Path("/workspace/agent-home").exists()
        assert not Path("/input").exists()
        assert not Path("/solution/solve.sh").exists()
        assert b"must-not-cross" not in patch
    except Exception as exc:
        return fail(str(exc))

    print("PASS: separate verifier received only the trusted normalized handoff")
    REWARD_PATH.write_text("1", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
