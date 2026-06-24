#!/usr/bin/env python3
"""Verifica que los slugs de los modelos nuevos funcionan en OpenRouter."""
import requests, pathlib, time

KEY = pathlib.Path("openrouter_key.txt").read_text().strip()
URL = "https://openrouter.ai/api/v1/chat/completions"

CANDIDATES = [
    ("qwen/qwen3.7-plus",             "$0.32/$1.28"),
    ("google/gemini-3.1-flash-lite",  "$0.25/$1.50"),
    ("qwen/qwen3-coder-next",         "$0.11/$0.80"),
    ("tencent/hy3-preview",           "$0.066/$0.26"),
    ("qwen/qwen3-coder",              "$0.22/$1.80"),   # Qwen3 Coder 480B A35B
    ("deepseek/deepseek-v4-pro",      "$0.435/$0.87"),
    ("z-ai/glm-5.2",                  "$1.00/$4.00"),
    ("minimax/minimax-m2.7",          "$0.25/$1.00"),
]

MSG = [{"role": "user", "content": "Reply with exactly: OK"}]

print(f"{'SLUG':<40} {'PRECIO':>14}  {'RESULTADO'}")
print("-" * 75)
for slug, price in CANDIDATES:
    try:
        t0 = time.time()
        r = requests.post(URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={"model": slug, "messages": MSG, "max_tokens": 200, "temperature": 0},
            timeout=30)
        elapsed = time.time() - t0
        if r.status_code == 200:
            data = r.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if content:
                print(f"{slug:<40} {price:>14}  OK ({elapsed:.1f}s) -> '{content.strip()[:40]}'")
            else:
                print(f"{slug:<40} {price:>14}  EMPTY_RESPONSE:")
                print(f"  full: {str(data)[:400]}")
        else:
            err = r.json().get("error", {}).get("message", r.text)[:80]
            print(f"{slug:<40} {price:>14}  FAIL HTTP {r.status_code}: {err}")
    except Exception as e:
        print(f"{slug:<40} {price:>14}  ERROR: {e}")
