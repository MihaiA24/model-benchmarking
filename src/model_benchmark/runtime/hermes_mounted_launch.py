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
_STOCK_ELF_INTERPRETER = "/lib64/ld-linux-x86-64.so.2"
_STOCK_PYTHON_PATH = "/usr/bin/python3.13"
_STOCK_PYTHON_IDENTITY = (
    "artifact:sha256:4703a3d15898c0b5d81c3f939e93bdd8ca6116342093fb160ab1e01860dd7d8b"
)
_STOCK_PYTHON_BYTES = 6_812_336
_STOCK_LOADER_PATH = "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
_STOCK_LOADER_IDENTITY = (
    "artifact:sha256:438c546d8e8cc48496bf3a95f753051afd9db66a629a74e31a9ded71586b56e0"
)
_STOCK_LOADER_BYTES = 225_672
_RELOCATED_PYTHON_PATH = "/mb-runtime/python"
_RELOCATED_LOADER_PATH = "/mb-runtime/ld.so"


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


def relocation_contract() -> dict[str, object]:
    return {
        "elf_interpreter": {
            "before": _STOCK_ELF_INTERPRETER,
            "after": _RELOCATED_LOADER_PATH,
        },
        "loader": {
            "source_path": _STOCK_LOADER_PATH,
            "source_identity": _STOCK_LOADER_IDENTITY,
            "source_bytes": _STOCK_LOADER_BYTES,
            "runtime_path": _RELOCATED_LOADER_PATH,
        },
        "python": {
            "source_path": _STOCK_PYTHON_PATH,
            "source_identity": _STOCK_PYTHON_IDENTITY,
            "source_bytes": _STOCK_PYTHON_BYTES,
            "runtime_path": _RELOCATED_PYTHON_PATH,
        },
    }


def _identity(data: bytes) -> str:
    return f"artifact:sha256:{hashlib.sha256(data).hexdigest()}"


def _publish_exclusive(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
    try:
        os.fchmod(descriptor, 0o500)
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written == 0:
                raise OSError("short write while relocating Hermes runtime")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    if _digest(path) != _identity(data):
        path.unlink(missing_ok=True)
        raise OSError("relocated Hermes runtime failed read-back verification")


def _materialize_relocated_python(
    mounted_root: Path,
) -> tuple[Path, tuple[Path, ...]]:
    python_source = mounted_root / _STOCK_PYTHON_PATH.removeprefix("/")
    loader_source = mounted_root / _STOCK_LOADER_PATH.removeprefix("/")
    python_bytes = python_source.read_bytes()
    loader_bytes = loader_source.read_bytes()
    if (
        len(python_bytes) != _STOCK_PYTHON_BYTES
        or _identity(python_bytes) != _STOCK_PYTHON_IDENTITY
        or len(loader_bytes) != _STOCK_LOADER_BYTES
        or _identity(loader_bytes) != _STOCK_LOADER_IDENTITY
    ):
        raise ValueError("mounted Hermes runtime does not match its declaration")

    before = _STOCK_ELF_INTERPRETER.encode() + b"\0"
    after = _RELOCATED_LOADER_PATH.encode() + b"\0"
    if len(after) > len(before) or python_bytes.count(before) != 1:
        raise ValueError("stock Hermes Python ELF interpreter is not relocatable")
    relocated_python = python_bytes.replace(before, after.ljust(len(before), b"\0"))
    python_path = Path(_RELOCATED_PYTHON_PATH)
    loader_path = Path(_RELOCATED_LOADER_PATH)
    published: list[Path] = []
    try:
        _publish_exclusive(loader_path, loader_bytes)
        published.append(loader_path)
        _publish_exclusive(python_path, relocated_python)
        published.append(python_path)
    except BaseException:
        for path in reversed(published):
            path.unlink(missing_ok=True)
        raise
    return python_path, (python_path, loader_path)

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


def main(argv: list[str] | None = None) -> int:
    raw_arguments = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--artifact-identity", required=True)
    arguments = parser.parse_args(raw_arguments)
    mounted_root = Path("/opt/model-benchmark-condition")
    mounted_hermes = mounted_root / "opt/hermes"
    shim = mounted_hermes / "bin/hermes"
    real = mounted_hermes / ".venv/bin/hermes"
    relocated_paths: tuple[Path, ...] = ()
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
        python, relocated_paths = _materialize_relocated_python(mounted_root)
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
            "runtime_relocation": relocation_contract(),
            "schema_version": 1,
            "skills_injection": False,
            "transport": "oneshot-argument-with-native-tools",
            "workspace": str(Path.cwd()),
        }
        (evidence / "hermes-delivery.json").write_text(
            json.dumps(delivery, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        library_path = ":".join(
            str(path)
            for path in (
                mounted_root / "lib/x86_64-linux-gnu",
                mounted_root / "usr/lib/x86_64-linux-gnu",
                mounted_root / "usr/local/lib",
            )
        )
        environment = {
            **os.environ,
            "HERMES_DISABLE_LAZY_INSTALLS": "1",
            "HERMES_HOME": str(hermes_home),
            "HERMES_INFERENCE_MODEL": model,
            "HERMES_INFERENCE_PROVIDER": _PROVIDER_ARGUMENT,
            "HERMES_TUI_DIR": str(mounted_hermes / "ui-tui"),
            "HERMES_WEB_DIST": str(mounted_hermes / "hermes_cli/web_dist"),
            "LD_LIBRARY_PATH": library_path,
            "PATH": (
                f"{mounted_hermes / 'bin'}:{mounted_hermes / '.venv/bin'}:"
                f"{os.environ.get('PATH', '')}"
            ),
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
                str(python),
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
    finally:
        for path in relocated_paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
