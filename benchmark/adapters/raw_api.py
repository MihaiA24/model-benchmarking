"""Legacy direct OpenRouter chat-completions adapter."""

from __future__ import annotations

import re
import time

import requests

from benchmark.adapters.base import AdapterResult
from benchmark.models import PRICES
from benchmark.util import benchmark_env, secret_file

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def read_openrouter_key() -> str:
    key = benchmark_env().get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    key_file = secret_file("openrouter_key.txt")
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


def extract_code(text: str) -> str:
    match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.S)
    return match.group(1) if match else text


class RawApiAdapter:
    name = "raw_api"

    def __init__(self, *, temperature: float = 0.2, max_tokens: int = 4096):
        self.temperature = temperature
        self.max_tokens = max_tokens

    def run(self, *, task, workdir: Path, model: str, prompt: str, transcript_path: Path, timeout_s: int) -> AdapterResult:
        key = read_openrouter_key()
        if not key or key == "PEGA_AQUI_TU_KEY":
            raise RuntimeError("Falta la API key en OPENROUTER_API_KEY u openrouter_key.txt")

        target = workdir / task.target_file
        file_content = target.read_text(encoding="utf-8")
        user_msg = f"{prompt}\n\n--- FICHERO ACTUAL ---\n{file_content}"

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
        in_tokens = usage.get("prompt_tokens", 0)
        out_tokens = usage.get("completion_tokens", 0)
        price_in, price_out = PRICES.get(model, (0, 0))
        cost = in_tokens / 1e6 * price_in + out_tokens / 1e6 * price_out

        transcript_path.write_text(text, encoding="utf-8")
        target.write_text(extract_code(text), encoding="utf-8")

        return AdapterResult(
            text=text,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            cost_usd=round(cost, 6),
            model_calls=1,
            telemetry_note="openrouter_usage; cost_from_price_table",
            latency_s=latency,
            transcript_path=str(transcript_path),
        )
