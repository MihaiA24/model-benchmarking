from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CLI = Path(sys.executable).with_name("model-benchmark-scenario")


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, "--json", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
