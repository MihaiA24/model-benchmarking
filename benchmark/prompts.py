"""Prompt rendering for raw API and agent-harness runs."""

from __future__ import annotations

import re
import shlex

_OUTPUT_INSTRUCTIONS = [
    r"Devuelve SOLO el contenido completo y corregido del fichero, en un unico bloque de codigo\." ,
    r"Devuelve SOLO el contenido completo y corregido del fichero, en un único bloque de código\." ,
    r"Return ONLY the complete corrected file content in a single code block\.",
    r"Return ONLY the complete corrected Python file in a single code block\.",
]


def raw_api_prompt(task) -> str:
    """Prompt used by the legacy raw OpenRouter API adapter."""
    return task.prompt


def _strip_raw_output_contract(prompt: str) -> str:
    stripped = prompt
    for pattern in _OUTPUT_INSTRUCTIONS:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _fmt_cmd(cmd: list[str] | None) -> str:
    if not cmd:
        return "(same as build)"
    return shlex.join(str(part) for part in cmd)


def agent_prompt(task) -> str:
    """Prompt used when a coding-agent harness edits the workdir directly."""
    task_details = _strip_raw_output_contract(task.prompt)
    return f"""You are running inside an isolated benchmark workdir for task `{task.name}`.

Goal:
{task_details}

Primary target file: `{task.target_file}`

Rules:
- Modify files in the current working directory only.
- Make the minimum code changes needed for this task.
- Do not modify benchmark result CSVs, runner files, or files outside this workdir.
- Do not use web search, external MCP services, package installs, or network calls.
- You may read files, edit files, and run local build commands.
- Leave the fixed files on disk. Your final answer should be a short status summary, not a full file dump.

Verification command the benchmark runner will execute after you finish:
- Build: {_fmt_cmd(task.build_cmd)}
"""
