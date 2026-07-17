from __future__ import annotations

import shlex
import tempfile
from pathlib import Path
from typing import override

from harbor.agents.installed.base import BaseInstalledAgent


_CONDITIONS = frozenset({"omp", "opencode", "hermes", "raw-api"})
_MOUNT = "/opt/model-benchmark-condition"


class FunctionalV1ConditionAgent(BaseInstalledAgent):
    """Pinned Harbor installed-agent seam for one Functional V1 cell."""

    def __init__(
        self,
        *args: object,
        condition: str,
        entrypoint: str,
        artifact_identity: str,
        target_path: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        if condition not in _CONDITIONS:
            raise ValueError("unknown Functional V1 condition")
        if not entrypoint.startswith(f"{_MOUNT}/") or "\x00" in entrypoint:
            raise ValueError(
                "condition entrypoint must be inside the selected image mount"
            )
        if not artifact_identity.startswith("artifact:sha256:"):
            raise ValueError("condition artifact identity is invalid")
        if condition == "raw-api" and not target_path:
            raise ValueError("Raw API requires the Scenario target path")
        if condition != "raw-api" and target_path:
            raise ValueError("only Raw API accepts a target path")
        self._condition = condition
        self._entrypoint = entrypoint
        self._artifact_identity = artifact_identity
        self._target_path = target_path

    @staticmethod
    @override
    def name() -> str:
        return "model-benchmark-condition"

    @override
    def version(self) -> str:
        return "1.0.0"

    @override
    async def install(self, environment) -> None:
        command = (
            f"test -x {shlex.quote(self._entrypoint)} && "
            f"test ! -e {_MOUNT}/verifier && "
            f"mkdir -p /logs/agent/home && "
            f"chmod -R a+rwX /logs/agent/home"
        )
        result = await environment.exec(command, user="root", timeout_sec=30)
        if result.return_code != 0:
            raise RuntimeError("selected condition image mount failed closed preflight")
        # The condition process runs as 65532 while the main service drops
        # every capability, so root cannot chown; each launch script creates
        # its own .model-benchmark, so only prove the home is writable by the
        # condition user here.
        ownership = await environment.exec(
            "touch /logs/agent/home/.writable"
            " && rm /logs/agent/home/.writable",
            user="65532:65532",
            timeout_sec=30,
        )
        if ownership.return_code != 0:
            raise RuntimeError("condition home ownership could not be established")

    def _command(self) -> tuple[str, dict[str, str]]:
        arguments = [
            self._entrypoint,
            "--condition",
            self._condition,
            "--artifact-identity",
            self._artifact_identity,
        ]
        if self._target_path:
            arguments.extend(["--target-path", self._target_path])
        return shlex.join(arguments), {
            **self.extra_env,
            "HOME": "/logs/agent/home",
            "XDG_CACHE_HOME": "/logs/agent/home/.cache",
            "XDG_CONFIG_HOME": "/logs/agent/home/.config",
            "XDG_DATA_HOME": "/logs/agent/home/.local/share",
        }

    @override
    async def run(self, instruction: str, environment, context) -> None:
        with tempfile.TemporaryDirectory(prefix="model-benchmark-brief-") as temporary:
            source = Path(temporary) / "instruction.md"
            source.write_text(instruction, encoding="utf-8", newline="")
            destination = "/tmp/model-benchmark-instruction.md"
            await environment.upload_file(source, destination)

        command, execution_environment = self._command()
        result = await environment.exec(
            f"{command} < {shlex.quote(destination)}",
            cwd="/workspace/repository",
            env=execution_environment,
            timeout_sec=None,
        )
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "stdout.bin").write_bytes((result.stdout or "").encode())
        (self.logs_dir / "stderr.bin").write_bytes((result.stderr or "").encode())
        context.metadata = {
            "condition": self._condition,
            "exit_code": result.return_code,
            "selected_artifact_identity": self._artifact_identity,
        }
