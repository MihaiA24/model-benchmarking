"""Adapters for coding-agent CLI harnesses."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark.adapters.base import AdapterResult
from benchmark.models import PRICES
from benchmark.util import benchmark_env


@dataclass
class CliTelemetry:
    in_tokens: int | str = ""
    out_tokens: int | str = ""
    cost_usd: float | str = ""
    model_calls: int | str = ""
    note: str = ""


def _write_transcript(transcript_path: Path, *, display_cmd: list[str], result: subprocess.CompletedProcess[str] | None, error: BaseException | None = None) -> None:
    lines = [
        "COMMAND:",
        " ".join(display_cmd),
        "",
    ]
    if result is not None:
        lines.extend([
            f"EXIT: {result.returncode}",
            "",
            "STDOUT:",
            result.stdout or "",
            "",
            "STDERR:",
            result.stderr or "",
        ])
    if error is not None:
        lines.extend(["ERROR:", repr(error)])
    transcript_path.write_text("\n".join(lines), encoding="utf-8")


def _json_lines(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_number(data: dict[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return value
    return None


def _cost_number(data: dict[str, Any]) -> float | None:
    value = _first_number(data, "cost_usd", "costUSD", "totalCost", "cost")
    if value is not None:
        return float(value)
    cost = data.get("cost")
    if isinstance(cost, dict):
        total = _first_number(cost, "total", "totalCost", "usd")
        if total is not None:
            return float(total)
        parts = [
            _first_number(cost, "input"),
            _first_number(cost, "output"),
            _first_number(cost, "cacheRead"),
            _first_number(cost, "cacheWrite"),
        ]
        if any(part is not None for part in parts):
            return sum(float(part or 0) for part in parts)
    return None


def _usage_record(data: dict[str, Any]) -> tuple[int, int, float | None] | None:
    tokens = data.get("tokens")
    token_data = tokens if isinstance(tokens, dict) else data
    input_value = _first_number(token_data, "prompt_tokens", "input_tokens", "inputTokens", "inputTokenCount", "input")
    output_value = _first_number(
        token_data,
        "completion_tokens",
        "output_tokens",
        "outputTokens",
        "outputTokenCount",
        "output",
    )
    cost_value = _cost_number(data)
    if input_value is None and output_value is None:
        return None
    in_tokens = int(input_value or 0)
    out_tokens = int(output_value or 0)
    if in_tokens == 0 and out_tokens == 0 and not cost_value:
        return None
    return in_tokens, out_tokens, cost_value


def _event_usage_records(event: dict[str, Any]) -> list[tuple[int, int, float | None]]:
    records: list[tuple[int, int, float | None]] = []
    seen_sources: set[int] = set()
    for data in _walk_dicts(event):
        sources: list[dict[str, Any]] = []
        usage = data.get("usage")
        tokens = data.get("tokens")
        if isinstance(usage, dict):
            sources.append(usage)
            seen_sources.add(id(usage))
        if isinstance(tokens, dict):
            sources.append(data)
            seen_sources.add(id(tokens))
        if not sources:
            sources.append(data)
        for source in sources:
            if id(source) in seen_sources and source is data:
                continue
            seen_sources.add(id(source))
            record = _usage_record(source)
            if record is not None:
                records.append(record)
    return records


def _select_usage_records(events: list[dict[str, Any]]) -> list[tuple[int, int, float | None]]:
    for event_type in ("agent_end", "step_finish", "message_end", "turn_end"):
        records = [record for event in events if event.get("type") == event_type for record in _event_usage_records(event)]
        if records:
            return records

    records: list[tuple[int, int, float | None]] = []
    seen: set[tuple[int, int, float | None]] = set()
    for event in events:
        for record in _event_usage_records(event):
            key = (record[0], record[1], round(record[2], 8) if record[2] is not None else None)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def _extract_usage(stdout: str, stderr: str, model: str, harness: str) -> CliTelemetry:
    """Best-effort telemetry extraction from CLI JSON event streams."""
    events = list(_json_lines("\n".join([stdout, stderr])))
    if not events:
        return CliTelemetry(note=f"{harness}: no machine-readable usage telemetry")

    usage_records = _select_usage_records(events)

    if not usage_records:
        return CliTelemetry(note=f"{harness}: JSON output did not include token/cost telemetry")

    in_tokens = sum(record[0] for record in usage_records)
    out_tokens = sum(record[1] for record in usage_records)
    reported_costs = [record[2] for record in usage_records if record[2] is not None]
    if reported_costs:
        cost: float | str = round(sum(reported_costs), 6)
        note = f"{harness}: {len(usage_records)} usage record(s); cost_from_cli"
    else:
        price_in, price_out = PRICES.get(model, (0, 0))
        if price_in or price_out:
            cost = round(in_tokens / 1e6 * price_in + out_tokens / 1e6 * price_out, 6)
            note = f"{harness}: {len(usage_records)} usage record(s); cost_from_price_table"
        else:
            cost = ""
            note = f"{harness}: {len(usage_records)} usage record(s); missing price table"
    return CliTelemetry(
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_usd=cost,
        model_calls=len(usage_records),
        note=note,
    )

def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def _run_command(cmd: list[str], *, cwd: Path, timeout_s: int, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise subprocess.TimeoutExpired(cmd, timeout_s, output=exc.output or "", stderr=exc.stderr or "") from exc
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)



class _CliAdapter:
    name = "cli"

    def _command(self, *, workdir: Path, model: str, prompt: str, timeout_s: int) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    def _extract_telemetry(self, stdout: str, stderr: str, model: str) -> CliTelemetry:
        return _extract_usage(stdout, stderr, model, self.name)

    def run(self, *, task, workdir: Path, model: str, prompt: str, transcript_path: Path, timeout_s: int) -> AdapterResult:
        cmd, display_cmd = self._command(workdir=workdir, model=model, prompt=prompt, timeout_s=timeout_s)
        started = time.time()
        try:
            result = _run_command(cmd, cwd=workdir, timeout_s=timeout_s + 30, env=benchmark_env())
        except BaseException as exc:
            _write_transcript(transcript_path, display_cmd=display_cmd, result=None, error=exc)
            raise
        latency = time.time() - started
        _write_transcript(transcript_path, display_cmd=display_cmd, result=result)
        if result.returncode != 0:
            raise RuntimeError(f"{self.name} exited with {result.returncode}; see {transcript_path}")
        telemetry = self._extract_telemetry(result.stdout or "", result.stderr or "", model)
        return AdapterResult(
            text=(result.stdout or "") + (result.stderr or ""),
            in_tokens=telemetry.in_tokens,
            out_tokens=telemetry.out_tokens,
            cost_usd=telemetry.cost_usd,
            model_calls=telemetry.model_calls,
            telemetry_note=telemetry.note,
            latency_s=latency,
            transcript_path=str(transcript_path),
        )


class OmpAdapter(_CliAdapter):
    name = "omp"

    def _command(self, *, workdir: Path, model: str, prompt: str, timeout_s: int) -> tuple[list[str], list[str]]:
        tools = "read,bash,edit,write,grep,find,lsp"
        cmd = [
            "omp",
            "-p",
            f"--cwd={workdir}",
            f"--model={model}",
            "--mode=json",
            "--no-session",
            "--no-title",
            "--no-skills",
            "--no-rules",
            "--no-extensions",
            f"--tools={tools}",
            "--auto-approve",
            "--approval-mode=yolo",
            f"--max-time={timeout_s}",
            prompt,
        ]
        return cmd, [*cmd[:-1], "<prompt>"]


class OpenCodeAdapter(_CliAdapter):
    name = "opencode"

    def _command(self, *, workdir: Path, model: str, prompt: str, timeout_s: int) -> tuple[list[str], list[str]]:
        cmd = [
            "opencode",
            "run",
            "--model",
            model,
            "--dir",
            str(workdir),
            "--format",
            "json",
            "--dangerously-skip-permissions",
            "--",
            prompt,
        ]
        return cmd, [*cmd[:-1], "<prompt>"]


class HermesAdapter(_CliAdapter):
    name = "hermes"

    def _extract_telemetry(self, stdout: str, stderr: str, model: str) -> CliTelemetry:
        return CliTelemetry(note="hermes: oneshot CLI does not expose per-run model call/token/cost telemetry")


    def _model_args(self, model: str) -> list[str]:
        if model.startswith("opencode-go/"):
            return ["--provider", "opencode-go", "--model", model.split("/", 1)[1]]
        return ["--model", model]


    def _command(self, *, workdir: Path, model: str, prompt: str, timeout_s: int) -> tuple[list[str], list[str]]:
        cmd = [
            "hermes",
            "-z",
            prompt,
            *self._model_args(model),
            "--toolsets",
            "terminal,file",
            "--yolo",
            "--accept-hooks",
            "--ignore-rules",
            "--ignore-user-config",
        ]
        return cmd, ["hermes", "-z", "<prompt>", *cmd[3:]]
