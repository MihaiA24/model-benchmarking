"""Small helpers shared by benchmark modules."""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(path: str | Path) -> Path:
    """Resolve a repo-relative path from any launch cwd."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def secret_file(name: str) -> Path:
    """Return a repo-root secret file path."""
    return REPO_ROOT / name


def dotenv_values(path: str | Path = ".env") -> dict[str, str]:
    """Read repo-local dotenv values without adding a runtime dependency."""
    env_path = repo_path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if item.startswith("export "):
            item = item[7:].strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or value == "":
            continue
        if value[0:1] == value[-1:] and value[0:1] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values



def safe_label(value: str) -> str:
    """Make a filesystem-safe label while keeping it readable."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def benchmark_env() -> dict[str, str]:
    """Environment for model CLIs and local verification commands."""
    env = dotenv_values()
    env.update(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("CI", "true")
    openrouter_key = secret_file("openrouter_key.txt")
    if not env.get("OPENROUTER_API_KEY") and openrouter_key.exists():
        env["OPENROUTER_API_KEY"] = openrouter_key.read_text(encoding="utf-8").strip()
    opencode_key = secret_file("opencode_key.txt")
    if env.get("OPENCODE_API_KEY") and not env.get("OPENCODE_GO_API_KEY"):
        env["OPENCODE_GO_API_KEY"] = env["OPENCODE_API_KEY"]
    elif env.get("OPENCODE_GO_API_KEY") and not env.get("OPENCODE_API_KEY"):
        env["OPENCODE_API_KEY"] = env["OPENCODE_GO_API_KEY"]
    elif not env.get("OPENCODE_API_KEY") and not env.get("OPENCODE_GO_API_KEY") and opencode_key.exists():
        key = opencode_key.read_text(encoding="utf-8").strip()
        env["OPENCODE_API_KEY"] = key
        env["OPENCODE_GO_API_KEY"] = key
    return env
