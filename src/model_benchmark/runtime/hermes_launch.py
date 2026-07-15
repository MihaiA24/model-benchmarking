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
_PROVIDER_ARGUMENT = f"custom:{_PROVIDER_ID}"
_CONTAINER_HOME = "/opt/data"
_CONTAINER_WORKSPACE = "/workspace"


def _artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
    return f"artifact:sha256:{digest.hexdigest()}"


def _provider_config(*, base_url: str, model: str) -> dict[str, object]:
    return {
        "model": {
            "api_mode": "chat_completions",
            "base_url": base_url,
            "default": model,
            "provider": _PROVIDER_ARGUMENT,
        },
        "providers": {
            _PROVIDER_ID: {
                "api": base_url,
                "default_model": model,
                "key_env": "MODEL_BENCHMARK_PROXY_TOKEN",
                "name": "Model Benchmark Credential Proxy",
                "transport": "chat_completions",
            }
        },
    }


def _write_config(home: Path, *, base_url: str, model: str) -> bytes:
    destination = home / ".hermes" / "config.yaml"
    destination.parent.mkdir(mode=0o700)
    data = json.dumps(
        _provider_config(base_url=base_url, model=model),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    destination.write_bytes(data)
    destination.chmod(0o600)
    return data


def _valid_usage(path: Path, *, model: str) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict):
        return False
    integer_fields = ("api_calls", "input_tokens", "output_tokens", "total_tokens")
    return (
        value.get("completed") is True
        and value.get("failed") is False
        and value.get("model") == model
        and isinstance(value.get("provider"), str)
        and all(
            isinstance(value.get(field), int) and not isinstance(value.get(field), bool)
            for field in integer_fields
        )
    )


def _run_hermes(
    docker: Path,
    image_reference: str,
    artifact_container_path: str,
    brief: str,
    usage_path: Path,
    *,
    home: Path,
    model: str,
) -> int:
    container_usage_path = f"{_CONTAINER_HOME}/.model-benchmark/{usage_path.name}"
    completed = subprocess.run(
        [
            str(docker),
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network",
            "host",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            f"HOME={_CONTAINER_HOME}",
            "--env",
            f"HERMES_HOME={_CONTAINER_HOME}/.hermes",
            "--env",
            "HERMES_DISABLE_LAZY_INSTALLS=1",
            "--env",
            f"HERMES_INFERENCE_MODEL={model}",
            "--env",
            f"HERMES_INFERENCE_PROVIDER={_PROVIDER_ARGUMENT}",
            "--env",
            "MODEL_BENCHMARK_PROXY_TOKEN",
            "--volume",
            f"{home}:{_CONTAINER_HOME}",
            "--volume",
            f"{Path.cwd()}:{_CONTAINER_WORKSPACE}",
            "--workdir",
            _CONTAINER_WORKSPACE,
            "--entrypoint",
            artifact_container_path,
            image_reference,
            "--ignore-rules",
            "-z",
            brief,
            "--provider",
            _PROVIDER_ARGUMENT,
            "--model",
            model,
            "--usage-file",
            container_usage_path,
        ],
        cwd=Path.cwd(),
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    sys.stdout.buffer.write(completed.stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(completed.stderr)
    sys.stderr.buffer.flush()
    forbidden_auth = (
        home / ".hermes" / ".env",
        home / ".hermes" / "auth.json",
    )
    if (
        completed.returncode != 0
        or not _valid_usage(usage_path, model=model)
        or any(path.exists() or path.is_symlink() for path in forbidden_auth)
    ):
        return _UNQUALIFIED_EXIT
    return 0


def _write_delivery_evidence(
    destination: Path,
    *,
    base_url: str,
    brief: bytes,
    config: bytes,
    image_identity: str,
    model: str,
) -> None:
    value = {
        "auth_persistence": False,
        "brief_sha256": f"sha256:{hashlib.sha256(brief).hexdigest()}",
        "config_sha256": f"sha256:{hashlib.sha256(config).hexdigest()}",
        "image_identity": image_identity,
        "memory_injection": False,
        "model": model,
        "provider": _PROVIDER_ID,
        "proxy_base_url": base_url,
        "rules_injection": False,
        "runtime_installation": False,
        "schema_version": 1,
        "skills_injection": False,
        "transport": "oneshot-argument-with-native-tools",
        "workspace": str(Path.cwd()),
    }
    destination.write_bytes(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    destination.chmod(0o600)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--docker", required=True, type=Path)
    parser.add_argument("--hermes", required=True, type=Path)
    parser.add_argument("--artifact-identity", required=True)
    parser.add_argument("--artifact-container-path", required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--image-identity", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    expected_identity = arguments.artifact_identity
    image_digest = arguments.image_identity.removeprefix("oci-image:sha256:")
    if (
        not expected_identity.startswith("artifact:sha256:")
        or len(image_digest) != 64
        or arguments.image_reference.rsplit("@sha256:", 1)[-1] != image_digest
        or not arguments.docker.is_file()
        or not os.access(arguments.docker, os.X_OK)
        or arguments.artifact_container_path != "/opt/hermes/bin/hermes"
    ):
        return _UNQUALIFIED_EXIT
    try:
        if _artifact_digest(arguments.hermes) != expected_identity:
            return _UNQUALIFIED_EXIT
        brief_bytes = sys.stdin.buffer.read()
        brief = brief_bytes.decode("utf-8", errors="strict")
        if brief.startswith("\ufeff"):
            return _UNQUALIFIED_EXIT
        home = Path(os.environ["HOME"])
        base_url = os.environ["MODEL_BENCHMARK_PROXY_BASE_URL"]
        model = os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"]
        if not base_url or not model or any(
            ord(character) < 32 for character in base_url + model
        ):
            return _UNQUALIFIED_EXIT
        evidence = home / ".model-benchmark"
        evidence.mkdir(mode=0o700)
        config = _write_config(home, base_url=base_url, model=model)
        _write_delivery_evidence(
            evidence / "hermes-delivery.json",
            base_url=base_url,
            brief=brief_bytes,
            config=config,
            image_identity=arguments.image_identity,
            model=model,
        )
        exit_code = _run_hermes(
            arguments.docker,
            arguments.image_reference,
            arguments.artifact_container_path,
            brief,
            evidence / "hermes-usage.json",
            home=home,
            model=model,
        )
        if _artifact_digest(arguments.hermes) != expected_identity:
            return _UNQUALIFIED_EXIT
        return exit_code
    except (KeyError, OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return _UNQUALIFIED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
