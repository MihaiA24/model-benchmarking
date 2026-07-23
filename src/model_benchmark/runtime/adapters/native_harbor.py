from __future__ import annotations

import json
import os
import shlex
from typing import override

import yaml
from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.agents.installed.hermes import Hermes
from harbor.agents.installed.opencode import OpenCode
from harbor.agents.installed.pi import Pi


_MODELS = ("deepseek-v4-flash", "minimax-m3", "hy3")


class OpenCodeGoAgent(OpenCode):
    """OpenCode Go with a stable NVM default in Node-based task images."""

    @override
    async def install(self, environment) -> None:
        await super().install(environment)
        await self.exec_as_agent(
            environment,
            command=". \"$HOME/.nvm/nvm.sh\" && nvm alias default 22 >/dev/null",
        )

    @override
    async def run(self, instruction: str, environment, context) -> None:
        self._instruction = instruction
        env = {
            "OPENCODE_API_KEY": os.environ["OPENCODE_API_KEY"],
            "OPENCODE_FAKE_VCS": "git",
        }
        if skills_command := self._build_register_skills_command():
            await self.exec_as_agent(environment, command=skills_command, env=env)
        if mcp_command := self._build_register_config_command():
            await self.exec_as_agent(environment, command=mcp_command, env=env)
        cli_flags = self.build_cli_flags()
        await self.exec_as_agent(
            environment,
            command=(
                ". ~/.nvm/nvm.sh; "
                f"opencode --model={self.model_name} run --format=json "
                f"{(cli_flags + ' ') if cli_flags else ''}"
                "--thinking --dangerously-skip-permissions -- "
                f"{shlex.quote(instruction)} 2>&1 </dev/null | "
                "stdbuf -oL tee /logs/agent/opencode.txt"
            ),
            env=env,
        )
        if messages := self._error_messages():
            raise NonZeroAgentExitCodeError(
                "OpenCode emitted error event(s): " + "; ".join(messages[:3])
            )


class OpenCodeGoPi(Pi):
    """Pi routed through OpenCode Go's Chat Completions endpoint."""

    @override
    async def install(self, environment) -> None:
        await super().install(environment)
        config = json.dumps(
            {
                "providers": {
                    "openai": {
                        "api": "openai-completions",
                        "apiKey": "$OPENAI_API_KEY",
                        "authHeader": True,
                        "baseUrl": "https://opencode.ai/zen/go/v1",
                        "headers": {"User-Agent": "pi-coding-agent/0.73.1"},
                        "compat": {
                            "supportsDeveloperRole": False,
                            "supportsReasoningEffort": False,
                        },
                        "models": [
                            {
                                "id": model,
                                "contextWindow": 375000,
                                "maxTokens": 64000,
                            }
                            for model in _MODELS
                        ],
                    }
                }
            },
            separators=(",", ":"),
        )
        await self.exec_as_agent(
            environment,
            command=(
                "mkdir -p \"$HOME/.pi/agent\" && "
                f"printf '%s\\n' {shlex.quote(config)} > \"$HOME/.pi/agent/models.json\" && "
                ". \"$HOME/.nvm/nvm.sh\" && nvm alias default 22 >/dev/null"
            ),
        )

    @override
    async def run(self, instruction: str, environment, context) -> None:
        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Model name must be in the format provider/model_name")
        model = self.model_name.split("/", 1)[1]
        env = {"OPENAI_API_KEY": os.environ["OPENCODE_API_KEY"]}
        if skills_command := self._build_register_skills_command():
            await self.exec_as_agent(environment, command=skills_command)
        cli_flags = self.build_cli_flags()
        await self.exec_as_agent(
            environment,
            command=(
                ". ~/.nvm/nvm.sh; pi --print --mode json --no-session "
                f"--provider openai --model {model} "
                f"{(cli_flags + ' ') if cli_flags else ''}"
                f"{shlex.quote(instruction)} 2>&1 </dev/null | "
                f"grep -v '\"type\":\"message_update\"' | "
                f"stdbuf -oL tee /logs/agent/{self._OUTPUT_FILENAME}"
            ),
            env=env,
        )


class OpenCodeGoHermes(Hermes):
    """Hermes routed through OpenCode Go's Chat Completions endpoint."""

    @override
    async def run(self, instruction: str, environment, context) -> None:
        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Model name must be in the format provider/model_name")
        model = self.model_name.split("/", 1)[1]
        provider = "custom:opencode-go"
        config = yaml.safe_load(self._build_config_yaml(model))
        config["model"] = {
            "api_mode": "chat_completions",
            "base_url": "https://opencode.ai/zen/go/v1",
            "default": model,
            "provider": provider,
        }
        config["providers"] = {
            "opencode-go": {
                "api": "https://opencode.ai/zen/go/v1",
                "default_model": model,
                "key_env": "OPENAI_API_KEY",
                "name": "OpenCode Go",
                "transport": "chat_completions",
            }
        }
        rendered = yaml.dump(config, default_flow_style=False)
        env = {
            "HARBOR_INSTRUCTION": instruction,
            "HERMES_HOME": "/tmp/hermes",
            "HERMES_INFERENCE_MODEL": model,
            "HERMES_INFERENCE_PROVIDER": provider,
            "OPENAI_API_KEY": os.environ["OPENCODE_API_KEY"],
            "TERMINAL_ENV": "local",
        }
        await self.exec_as_agent(
            environment,
            command=(
                "mkdir -p /tmp/hermes && "
                f"cat > /tmp/hermes/config.yaml << 'EOF'\n{rendered}EOF"
            ),
            env=env,
            timeout_sec=10,
        )
        await self.exec_as_agent(
            environment,
            command=(
                "export PATH=\"$HOME/.local/bin:$PATH\" && "
                "hermes --yolo chat -q \"$HARBOR_INSTRUCTION\" -Q "
                f"--provider {shlex.quote(provider)} --model {shlex.quote(model)} "
                "2>&1 | stdbuf -oL tee /logs/agent/hermes.txt"
            ),
            env=env,
        )
