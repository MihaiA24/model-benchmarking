#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


_UNQUALIFIED_EXIT = 78
_PROVIDER_ID = "model-benchmark-proxy"


def _artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
    return f"artifact:sha256:{digest.hexdigest()}"


def _provider_config(*, base_url: str, model: str) -> dict[str, object]:
    return {
        "autoupdate": False,
        "mcp": {},
        "plugin": [],
        "provider": {
            _PROVIDER_ID: {
                "models": {model: {"name": model}},
                "name": "Model Benchmark Credential Proxy",
                "npm": "@ai-sdk/openai-compatible",
                "options": {
                    "apiKey": "{env:MODEL_BENCHMARK_PROXY_TOKEN}",
                    "baseURL": base_url,
                },
            }
        },
        "share": "disabled",
    }


def _write_config(home: Path, *, base_url: str, model: str) -> Path:
    destination = home / ".model-benchmark" / "opencode.json"
    destination.parent.mkdir(mode=0o700)
    destination.write_bytes(
        json.dumps(
            _provider_config(base_url=base_url, model=model),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    destination.chmod(0o600)
    return destination


def _valid_transcript(data: bytes) -> bool:
    lines = data.splitlines()
    if not lines:
        return False
    completed = False
    for line in lines:
        try:
            value = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            return False
        if value["type"] == "error":
            return False
        if value["type"] == "step_finish":
            completed = True
    return completed


def _run_opencode(
    opencode: Path,
    brief: bytes,
    transcript: Path,
    *,
    config_path: Path,
    model: str,
) -> int:
    environment = dict(os.environ)
    environment.update(
        {
            "OPENCODE_CONFIG": str(config_path),
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
        }
    )
    workspace = Path.cwd()
    completed = subprocess.run(
        [
            str(opencode),
            "run",
            "--format",
            "json",
            "--model",
            f"{_PROVIDER_ID}/{model}",
        ],
        cwd=workspace,
        env=environment,
        input=brief,
        stdout=subprocess.PIPE,
        stderr=None,
        check=False,
    )
    transcript.write_bytes(completed.stdout)
    transcript.chmod(0o600)
    sys.stdout.buffer.write(completed.stdout)
    sys.stdout.buffer.flush()
    auth_path = Path(os.environ["XDG_DATA_HOME"]) / "opencode" / "auth.json"
    if (
        completed.returncode != 0
        or not _valid_transcript(completed.stdout)
        or auth_path.exists()
        or auth_path.is_symlink()
    ):
        return _UNQUALIFIED_EXIT
    return 0


def _write_delivery_evidence(
    destination: Path,
    *,
    base_url: str,
    brief: bytes,
    model: str,
) -> None:
    value = {
        "auth_persistence": False,
        "brief_sha256": f"sha256:{hashlib.sha256(brief).hexdigest()}",
        "model": model,
        "provider": _PROVIDER_ID,
        "proxy_base_url": base_url,
        "schema_version": 1,
        "transport": "run-stdin-json-events",
        "workspace": str(Path.cwd()),
    }
    destination.write_bytes(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    destination.chmod(0o600)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--opencode", required=True, type=Path)
    parser.add_argument("--artifact-identity", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    expected_identity = arguments.artifact_identity
    if not expected_identity.startswith("artifact:sha256:"):
        return _UNQUALIFIED_EXIT
    try:
        if _artifact_digest(arguments.opencode) != expected_identity:
            return _UNQUALIFIED_EXIT
        brief = sys.stdin.buffer.read()
        text = brief.decode("utf-8", errors="strict")
        if text.startswith("\ufeff"):
            return _UNQUALIFIED_EXIT
        home = Path(os.environ["HOME"])
        base_url = os.environ["MODEL_BENCHMARK_PROXY_BASE_URL"]
        model = os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"]
        if not base_url or not model or any(
            ord(character) < 32 for character in base_url + model
        ):
            return _UNQUALIFIED_EXIT
        evidence = home / ".model-benchmark"
        config_path = _write_config(home, base_url=base_url, model=model)
        exit_code = _run_opencode(
            arguments.opencode,
            brief,
            evidence / "opencode-events.jsonl",
            config_path=config_path,
            model=model,
        )
        _write_delivery_evidence(
            evidence / "opencode-delivery.json",
            base_url=base_url,
            brief=brief,
            model=model,
        )
        if _artifact_digest(arguments.opencode) != expected_identity:
            return _UNQUALIFIED_EXIT
        return exit_code
    except (KeyError, OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return _UNQUALIFIED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
