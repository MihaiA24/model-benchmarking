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
_PROVIDER_PROTOCOL_ENV = "MODEL_BENCHMARK_PROVIDER_PROTOCOL"
_PROVIDER_API = {
    "openai-chat-completions": "openai-completions",
    "anthropic-messages": "anthropic-messages",
}
_NONINTERACTIVE_UI_METHODS = frozenset(
    {"cancel", "notify", "setStatus", "setTitle", "setWidget", "set_editor_text"}
)


def _artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
    return f"artifact:sha256:{digest.hexdigest()}"


def _write_models_config(
    home: Path, *, base_url: str, model: str, protocol: str
) -> None:
    provider: dict[str, object] = {
        "api": _PROVIDER_API[protocol],
        "apiKey": "MODEL_BENCHMARK_PROXY_TOKEN",
        "auth": "apiKey",
        "authHeader": True,
        "baseUrl": base_url,
        "models": [{"id": model, "name": model}],
    }
    config = {"providers": {_PROVIDER_ID: provider}}
    destination = home / ".omp" / "agent" / "models.yml"
    destination.parent.mkdir(parents=True, mode=0o700)
    data = json.dumps(config, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    destination.write_text(data + "\n", encoding="utf-8")
    destination.chmod(0o600)


def _prompt_frame(brief: str) -> bytes:
    return (
        json.dumps(
            {"id": "functional-v1-prompt", "message": brief, "type": "prompt"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _parse_frame(line: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(line.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()


def _run_rpc(omp: Path, brief: str, transcript: Path) -> int:
    command = [
        str(omp),
        "--mode",
        "rpc",
        "--model",
        f"{_PROVIDER_ID}/{os.environ['MODEL_BENCHMARK_PROVIDER_MODEL']}",
    ]
    process = subprocess.Popen(
        command,
        cwd=Path.cwd(),
        env=dict(os.environ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    if process.stdin is None or process.stdout is None:
        _terminate(process)
        return _UNQUALIFIED_EXIT

    ready = False
    prompt_accepted = False
    prompt_completed = False
    input_closed = False
    with transcript.open("wb") as recording:
        for line in process.stdout:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            recording.write(line)
            recording.flush()
            frame = _parse_frame(line)
            if frame is None:
                _terminate(process)
                return _UNQUALIFIED_EXIT
            frame_type = frame.get("type")
            if frame_type in {"host_tool_call", "host_uri_request"} or (
                frame_type == "extension_ui_request"
                and frame.get("method") not in _NONINTERACTIVE_UI_METHODS
            ):
                _terminate(process)
                return _UNQUALIFIED_EXIT
            if frame_type == "ready":
                if ready:
                    _terminate(process)
                    return _UNQUALIFIED_EXIT
                ready = True
                process.stdin.write(_prompt_frame(brief))
                process.stdin.flush()
            elif (
                frame_type == "response"
                and frame.get("id") == "functional-v1-prompt"
                and frame.get("command") == "prompt"
            ):
                if frame.get("success") is not True:
                    _terminate(process)
                    return _UNQUALIFIED_EXIT
                prompt_accepted = True
                data = frame.get("data")
                if isinstance(data, dict) and data.get("agentInvoked") is False:
                    prompt_completed = True
            elif (
                frame_type == "prompt_result"
                and frame.get("id") == "functional-v1-prompt"
                and frame.get("agentInvoked") is False
            ):
                prompt_completed = True
            elif frame_type == "agent_end":
                prompt_completed = True

            if prompt_completed and not input_closed:
                process.stdin.close()
                input_closed = True

    if not input_closed:
        process.stdin.close()
    exit_code = process.wait()
    if not ready or not prompt_accepted or not prompt_completed or exit_code != 0:
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
        "brief_sha256": f"sha256:{hashlib.sha256(brief).hexdigest()}",
        "model": model,
        "provider": _PROVIDER_ID,
        "proxy_base_url": base_url,
        "schema_version": 1,
        "transport": "rpc-prompt-jsonl",
        "workspace": str(Path.cwd()),
    }
    destination.write_bytes(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    destination.chmod(0o600)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--omp", required=True, type=Path)
    parser.add_argument("--artifact-identity", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    expected_identity = arguments.artifact_identity
    if not expected_identity.startswith("artifact:sha256:"):
        return _UNQUALIFIED_EXIT
    try:
        if _artifact_digest(arguments.omp) != expected_identity:
            return _UNQUALIFIED_EXIT
        brief_bytes = sys.stdin.buffer.read()
        brief = brief_bytes.decode("utf-8", errors="strict")
        if brief.startswith("\ufeff"):
            return _UNQUALIFIED_EXIT
        home = Path(os.environ["HOME"])
        base_url = os.environ["MODEL_BENCHMARK_PROXY_BASE_URL"]
        model = os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"]
        protocol = os.environ[_PROVIDER_PROTOCOL_ENV]
        if (
            protocol not in _PROVIDER_API
            or not base_url
            or not model
            or any(ord(character) < 32 for character in base_url + model)
        ):
            return _UNQUALIFIED_EXIT
        _write_models_config(home, base_url=base_url, model=model, protocol=protocol)
        evidence = home / ".model-benchmark"
        evidence.mkdir(mode=0o700)
        _write_delivery_evidence(
            evidence / "omp-delivery.json",
            base_url=base_url,
            brief=brief_bytes,
            model=model,
        )
        exit_code = _run_rpc(arguments.omp, brief, evidence / "omp-rpc.jsonl")
        if _artifact_digest(arguments.omp) != expected_identity:
            return _UNQUALIFIED_EXIT
        return exit_code
    except (KeyError, OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return _UNQUALIFIED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
