from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from model_benchmark.runtime.raw_api import RawApiMaterializer, RawApiRequest


_INVALID_ENVELOPE_EXIT = 78
# Digest-sealed materialization cap. The Submission boundary's capture policy
# enforces the real per-package byte budget downstream; this only bounds the
# single locked-file replacement read into memory.
_MAX_CONTENT_BYTES = 1 << 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--artifact-identity", required=True)
    parser.add_argument("--target-path", required=True)
    arguments = parser.parse_args(argv)
    try:
        module_identity = (
            f"artifact:sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"
        )
        if module_identity != arguments.artifact_identity:
            return _INVALID_ENVELOPE_EXIT
        brief = sys.stdin.buffer.read()
        brief.decode("utf-8", errors="strict")
        home = Path(os.environ["HOME"])
        evidence = home / ".model-benchmark"
        evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        result = RawApiMaterializer().materialize(
            RawApiRequest(
                proxy_base_url=os.environ["MODEL_BENCHMARK_PROXY_BASE_URL"],
                proxy_token=os.environ["MODEL_BENCHMARK_PROXY_TOKEN"],
                model=os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"],
                developer_brief=brief,
                repository=Path.cwd(),
                target_path=arguments.target_path,
                max_content_bytes=_MAX_CONTENT_BYTES,
            )
        )
        delivery = {
            "artifact_identity": arguments.artifact_identity,
            "brief_sha256": f"sha256:{hashlib.sha256(brief).hexdigest()}",
            "diagnostic_code": result.diagnostic_code,
            "outcome": result.outcome,
            "provider_model": os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"],
            "proxy_base_url": os.environ["MODEL_BENCHMARK_PROXY_BASE_URL"],
            "reason_code": result.reason_code,
            "request_count": result.request_count,
            "schema_version": 1,
            "target_path": arguments.target_path,
        }
        (evidence / "raw-api-delivery.json").write_text(
            json.dumps(delivery, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        return 0 if result.outcome == "ready-for-capture" else _INVALID_ENVELOPE_EXIT
    except (KeyError, OSError, UnicodeError, ValueError):
        return _INVALID_ENVELOPE_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
