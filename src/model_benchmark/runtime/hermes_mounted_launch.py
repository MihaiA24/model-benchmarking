from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


_UNQUALIFIED_EXIT = 78
_PROVIDER_ID = "model-benchmark-proxy"
_PROVIDER_ARGUMENT = f"custom:{_PROVIDER_ID}"
_TOOL_PATH_ENV = "MODEL_BENCHMARK_HERMES_TOOL_PATH"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return f"artifact:sha256:{digest.hexdigest()}"


def _config(base_url: str, model: str) -> dict[str, object]:
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


def _valid_usage(path: Path, model: str) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    integer_fields = ("api_calls", "input_tokens", "output_tokens", "total_tokens")
    return (
        isinstance(value, dict)
        and value.get("completed") is True
        and value.get("failed") is False
        and value.get("model") == model
        and all(
            isinstance(value.get(field), int) and not isinstance(value.get(field), bool)
            for field in integer_fields
        )
    )


def _run_hermes_entrypoint(arguments: list[str]) -> int:
    original_argv = sys.argv
    try:
        sys.argv = arguments
        try:
            runpy.run_path(arguments[0], run_name="__main__")
        except SystemExit as error:
            if error.code is None:
                return 0
            return error.code if isinstance(error.code, int) else 1
        return 0
    finally:
        sys.argv = original_argv


def _bootstrap_hermes(arguments: list[str]) -> int:
    """Run Hermes in its mounted Python while isolating native child tools."""
    tool_path = os.environ.get(_TOOL_PATH_ENV)
    if not arguments or not tool_path:
        return _UNQUALIFIED_EXIT
    original_environment = dict(os.environ)
    try:
        os.environ["PATH"] = tool_path
        for name in (_TOOL_PATH_ENV, "LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH"):
            os.environ.pop(name, None)
        return _run_hermes_entrypoint(arguments)
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def main(argv: list[str] | None = None) -> int:
    raw_arguments = sys.argv[1:] if argv is None else argv
    if raw_arguments[:1] == ["--bootstrap"]:
        return _bootstrap_hermes(raw_arguments[1:])
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--artifact-identity", required=True)
    arguments = parser.parse_args(raw_arguments)
    mounted_root = Path("/opt/model-benchmark-condition")
    mounted_hermes = mounted_root / "opt/hermes"
    # The real ELF, not the lib64 symlink: on absolute-symlink glibc layouts
    # the symlink escapes the read-only image mount into the scenario image
    # (issue #99).
    loader = mounted_root / "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
    library_path = ":".join(
        str(path)
        for path in (
            mounted_root / "lib/x86_64-linux-gnu",
            mounted_root / "usr/lib/x86_64-linux-gnu",
            mounted_root / "usr/local/lib",
        )
    )
    shim = mounted_hermes / "bin/hermes"
    python = mounted_root / "usr/bin/python3"
    real = mounted_hermes / ".venv/bin/hermes"
    try:
        if _digest(shim) != arguments.artifact_identity:
            return _UNQUALIFIED_EXIT
        brief_bytes = sys.stdin.buffer.read()
        brief = brief_bytes.decode("utf-8", errors="strict")
        if brief.startswith("\ufeff"):
            return _UNQUALIFIED_EXIT
        home = Path(os.environ["HOME"])
        base_url = os.environ["MODEL_BENCHMARK_PROXY_BASE_URL"]
        model = os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"]
        evidence = home / ".model-benchmark"
        evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        hermes_home = home / ".hermes"
        hermes_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = json.dumps(
            _config(base_url, model),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        config_path = hermes_home / "config.yaml"
        config_path.write_bytes(config)
        config_path.chmod(0o600)
        usage = evidence / "hermes-usage.json"
        delivery = {
            "auth_persistence": False,
            "brief_sha256": f"sha256:{hashlib.sha256(brief_bytes).hexdigest()}",
            "config_sha256": f"sha256:{hashlib.sha256(config).hexdigest()}",
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
        (evidence / "hermes-delivery.json").write_text(
            json.dumps(delivery, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "HERMES_DISABLE_LAZY_INSTALLS": "1",
            "HERMES_HOME": str(hermes_home),
            "HERMES_INFERENCE_MODEL": model,
            "HERMES_INFERENCE_PROVIDER": _PROVIDER_ARGUMENT,
            "HERMES_TUI_DIR": str(mounted_hermes / "ui-tui"),
            "HERMES_WEB_DIST": str(mounted_hermes / "hermes_cli/web_dist"),
            _TOOL_PATH_ENV: os.environ.get("PATH", os.defpath),
            "LD_LIBRARY_PATH": library_path,
            "PATH": f"{mounted_hermes / 'bin'}:{mounted_hermes / '.venv/bin'}:{os.environ.get('PATH', '')}",
            "PLAYWRIGHT_BROWSERS_PATH": str(mounted_hermes / ".playwright"),
            "PYTHONHOME": str(mounted_root / "usr"),
            "PYTHONPATH": ":".join(
                (
                    str(mounted_hermes),
                    str(mounted_hermes / ".venv/lib/python3.13/site-packages"),
                    str(mounted_root / "opt/model-benchmark-runtime"),
                )
            ),
        }
        completed = subprocess.run(
            [
                str(loader),
                "--library-path",
                library_path,
                str(python),
                "-m",
                "model_benchmark.runtime.hermes_mounted_launch",
                "--bootstrap",
                str(real),
                "--ignore-rules",
                "-z",
                brief,
                "--provider",
                _PROVIDER_ARGUMENT,
                "--model",
                model,
                "--usage-file",
                str(usage),
            ],
            cwd=Path.cwd(),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        sys.stdout.buffer.write(completed.stdout)
        sys.stderr.buffer.write(completed.stderr)
        forbidden = (hermes_home / ".env", hermes_home / "auth.json")
        if (
            completed.returncode != 0
            or not _valid_usage(usage, model)
            or any(path.exists() or path.is_symlink() for path in forbidden)
            or _digest(shim) != arguments.artifact_identity
        ):
            return _UNQUALIFIED_EXIT
        return 0
    except (KeyError, OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return _UNQUALIFIED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
