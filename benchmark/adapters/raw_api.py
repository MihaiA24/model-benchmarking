"""Direct single-shot API adapter for OpenRouter and OpenCode Go."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from pathlib import Path

import requests

from benchmark.adapters.base import AdapterResult
from benchmark.models import (
    PRICES,
    is_opencode_go_selector,
    opencode_go_model_id,
    opencode_go_selector,
)
from benchmark.util import benchmark_env, secret_file

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENCODE_CHAT_URL = "https://opencode.ai/zen/go/v1/chat/completions"
PLACEHOLDER_KEYS = {"", "PEGA_AQUI_TU_KEY"}
_CODE_BLOCK_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


@dataclass(frozen=True)
class ApiCallResult:
    text: str
    in_tokens: int
    out_tokens: int
    latency_s: float
    telemetry_note: str
    provider_backend: str
    api_backend: str
    pricing_model: str


def _read_key(env_names: tuple[str, ...], filename: str) -> str:
    env = benchmark_env()
    for env_name in env_names:
        key = env.get(env_name, "").strip()
        if key and key not in PLACEHOLDER_KEYS:
            return key
    key_file = secret_file(filename)
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key not in PLACEHOLDER_KEYS:
            return key
    return ""


def read_openrouter_key() -> str:
    return _read_key(("OPENROUTER_API_KEY",), "openrouter_key.txt")


def read_opencode_key() -> str:
    return _read_key(("OPENCODE_API_KEY", "OPENCODE_GO_API_KEY"), "opencode_key.txt")


class FormatError(RuntimeError):
    """Model response did not contain a parseable code block."""


def extract_code(text: str) -> str:
    if not text.strip():
        raise FormatError("format_error: empty model response")

    # Reasoning-model transcripts often include example snippets in <think> before
    # the final full-file answer. The benchmark should judge the submitted file,
    # not the first illustrative snippet.
    visible_text = _THINK_BLOCK_RE.sub("", text)
    matches = _CODE_BLOCK_RE.findall(visible_text) or _CODE_BLOCK_RE.findall(text)
    if not matches:
        raise FormatError("format_error: no code block found in model response")
    return matches[-1]

def _usage_tokens(usage: dict, *, input_key: str, output_key: str) -> tuple[int, int]:
    return int(usage.get(input_key) or 0), int(usage.get(output_key) or 0)


class RawApiAdapter:
    name = "raw_api"

    def __init__(self, *, temperature: float = 0.2, max_tokens: int = 4096):
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _call_openrouter(self, *, key: str, model: str, user_msg: str, timeout_s: int) -> ApiCallResult:
        started = time.time()
        response = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": user_msg}],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            timeout=timeout_s,
        )
        latency = time.time() - started
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        in_tokens, out_tokens = _usage_tokens(usage, input_key="prompt_tokens", output_key="completion_tokens")
        return ApiCallResult(
            text=text,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            latency_s=latency,
            telemetry_note="openrouter_usage; cost_from_price_table",
            provider_backend=model.split("/", 1)[0] if "/" in model else "openrouter",
            api_backend="openrouter_chat",
            pricing_model=model,
        )

    def _call_opencode_chat(self, *, key: str, model_id: str, user_msg: str, timeout_s: int) -> ApiCallResult:
        started = time.time()
        response = requests.post(
            OPENCODE_CHAT_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": user_msg}],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            timeout=timeout_s,
        )
        latency = time.time() - started
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        in_tokens, out_tokens = _usage_tokens(usage, input_key="prompt_tokens", output_key="completion_tokens")
        return ApiCallResult(
            text=text,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            latency_s=latency,
            telemetry_note="opencode_go_chat_api_usage; cost_from_price_table",
            provider_backend="opencode-go",
            api_backend="opencode_go_chat",
            pricing_model=opencode_go_selector(model_id),
        )


    def _call_api(self, *, model: str, user_msg: str, timeout_s: int) -> ApiCallResult:
        model_id = opencode_go_model_id(model)

        if is_opencode_go_selector(model):
            opencode_key = read_opencode_key()
            if not opencode_key:
                raise RuntimeError("Falta la API key en OPENCODE_API_KEY / OPENCODE_GO_API_KEY u opencode_key.txt")
            return self._call_opencode_chat(key=opencode_key, model_id=model_id, user_msg=user_msg, timeout_s=timeout_s)

        openrouter_key = read_openrouter_key()
        if openrouter_key:
            return self._call_openrouter(key=openrouter_key, model=model, user_msg=user_msg, timeout_s=timeout_s)

        if model_id:
            opencode_key = read_opencode_key()
            if not opencode_key:
                raise RuntimeError("Falta la API key en OPENCODE_API_KEY / OPENCODE_GO_API_KEY u opencode_key.txt")
            return self._call_opencode_chat(key=opencode_key, model_id=model_id, user_msg=user_msg, timeout_s=timeout_s)

        raise RuntimeError(f"Falta la API key en OPENROUTER_API_KEY u openrouter_key.txt; {model} no tiene fallback OpenCode Go")

    def run(self, *, task, workdir: Path, model: str, prompt: str, transcript_path: Path, timeout_s: int) -> AdapterResult:
        target = workdir / task.target_file
        file_content = target.read_text(encoding="utf-8")
        user_msg = f"{prompt}\n\n--- FICHERO ACTUAL ---\n{file_content}"

        call = self._call_api(model=model, user_msg=user_msg, timeout_s=timeout_s)
        if not call.text:
            transcript_path.write_text("", encoding="utf-8")
            raise RuntimeError("infrastructure_failure: empty model response")

        price_in, price_out = PRICES.get(call.pricing_model, (0, 0))
        cost = call.in_tokens / 1e6 * price_in + call.out_tokens / 1e6 * price_out

        transcript_path.write_text(call.text, encoding="utf-8")
        target.write_text(extract_code(call.text), encoding="utf-8")

        return AdapterResult(
            text=call.text,
            in_tokens=call.in_tokens,
            out_tokens=call.out_tokens,
            cost_usd=round(cost, 6),
            model_calls=1,
            adapter_model=call.pricing_model,
            provider_backend=call.provider_backend,
            api_backend=call.api_backend,
            pricing_model=call.pricing_model,
            telemetry_note=call.telemetry_note,
            latency_s=call.latency_s,
            transcript_path=str(transcript_path),
            capability_mode="single_shot",
            telemetry_trust="exact",
            tool_set="",
        )
