"""Common adapter types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class AdapterResult:
    """Normalized result from a benchmark harness invocation."""

    text: str
    in_tokens: int | str = ""
    out_tokens: int | str = ""
    cost_usd: float | str = ""
    model_calls: int | str = ""
    telemetry_note: str = ""
    latency_s: float = 0.0
    transcript_path: str = ""


class HarnessAdapter(Protocol):
    """Protocol implemented by raw API and CLI agent harnesses."""

    name: str

    def run(
        self,
        *,
        task,
        workdir: Path,
        model: str,
        prompt: str,
        transcript_path: Path,
        timeout_s: int,
    ) -> AdapterResult:
        """Run one benchmark attempt."""
