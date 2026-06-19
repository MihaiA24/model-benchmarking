#!/usr/bin/env python3
"""Re-run solo data-feat1-customer-ranking con fix de encoding."""
import time, shutil, subprocess, csv, pathlib, re, requests, stat, os, sys

KEY_FILE = pathlib.Path("openrouter_key.txt")
OPENROUTER_API_KEY = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "PEGA_AQUI_TU_KEY":
    raise SystemExit("Falta la API key en openrouter_key.txt")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = ["minimax/minimax-m3", "deepseek/deepseek-v4-flash", "z-ai/glm-4.7"]
PRICES = {
    "minimax/minimax-m3":         (0.30, 1.20),
    "deepseek/deepseek-v4-flash": (0.09, 0.18),
    "z-ai/glm-4.7":               (0.40, 1.75),
}
RUNS = 3
BASELINE = pathlib.Path("baselines/data-chinook")

TASKS = [
    {
        "name": "data-feat1-customer-ranking",
        "target_file": "feat1_customer_ranking.py",
        "prompt": (
            "Feature request: implement a SQL query using window functions to rank customers "
            "by total purchase amount within their country.\n\n"
            "Schema (relevant tables):\n"
            "  Customer(CustomerId, FirstName, LastName, Country, ...)\n"
            "  Invoice(InvoiceId, CustomerId, InvoiceDate, Total)\n\n"
            "Requirements:\n"
            "- TotalPurchases = SUM(Invoice.Total) per customer, rounded to 2 decimals\n"
            "- Rank = RANK() OVER (PARTITION BY Country ORDER BY TotalPurchases DESC)\n"
            "- Output columns (exact names): Country, CustomerId, FirstName, LastName, TotalPurchases, Rank\n"
            "- Order: Country ASC, Rank ASC\n"
            "- Save result to output_feat1.csv (already done in the template)\n\n"
            "Replace the placeholder query with the correct SQL. "
            "Return ONLY the complete corrected Python file in a single code block."
        ),
        "build_cmd": [sys.executable, "-m", "py_compile", "feat1_customer_ranking.py"],
        "test_cmd":  [sys.executable, "verify_feat1.py"],
    },
]

RESULTS = pathlib.Path("results")
CSV_PATH = RESULTS / "metrics_data.csv"


def call_model(model, file_content, prompt):
    user_msg = f"{prompt}\n\n--- FICHERO ACTUAL ---\n{file_content}"
    t0 = time.time()
    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={"model": model, "messages": [{"role": "user", "content": user_msg}], "temperature": 0.2},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    latency = time.time() - t0
    return data["choices"][0]["message"]["content"], data.get("usage", {}), latency


def extract_code(text):
    m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def _force_remove(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def run_checks(workdir, task):
    out = {}
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for label, cmd in [("build", task["build_cmd"]), ("test", task["test_cmd"])]:
        p = subprocess.run(cmd, cwd=workdir, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env)
        out[label] = (p.returncode == 0)
        if label == "test" and not out[label]:
            (workdir / "_test_output.txt").write_text(p.stdout + p.stderr, encoding="utf-8")
    return out


def main():
    # Elimina las 9 filas anteriores de feat1 (todas False por el bug de encoding)
    existing = []
    if CSV_PATH.exists():
        existing = [r for r in csv.DictReader(open(CSV_PATH, encoding='utf-8'))
                    if r['task'] != 'data-feat1-customer-ranking']
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        if existing:
            w = csv.DictWriter(f, fieldnames=existing[0].keys())
            w.writeheader(); w.writerows(existing)
        else:
            csv.writer(f).writerow(["task","model","run","build_ok","test_ok",
                                    "in_tok","out_tok","cost_usd","latency_s","workdir"])

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for task in TASKS:
            for model in MODELS:
                for run in range(1, RUNS + 1):
                    label = f"{task['name']}__{model.replace('/', '_')}__r{run}"
                    workdir = RESULTS / label
                    try:
                        if workdir.exists():
                            shutil.rmtree(workdir, onerror=_force_remove)
                        shutil.copytree(BASELINE, workdir)
                        target = workdir / task["target_file"]
                        text, usage, latency = call_model(model, target.read_text(encoding="utf-8"), task["prompt"])
                        target.write_text(extract_code(text), encoding="utf-8")
                        checks = run_checks(workdir, task)
                        it = usage.get("prompt_tokens", 0); ot = usage.get("completion_tokens", 0)
                        pin, pout = PRICES.get(model, (0, 0))
                        cost = it / 1e6 * pin + ot / 1e6 * pout
                        (workdir / "_raw_response.txt").write_text(text, encoding="utf-8")
                        w.writerow([task["name"], model, run, checks["build"], checks["test"],
                                    it, ot, round(cost, 4), round(latency, 1), str(workdir)])
                        print(f"{task['name']:32} | {model:32} | run {run} -> "
                              f"build={checks['build']} test={checks['test']} ${cost:.4f}")
                    except Exception as e:
                        w.writerow([task["name"], model, run, "ERROR", "ERROR", 0, 0, 0, 0, str(e)[:200]])
                        print(f"ERROR: {e}")

    print(f"\nListo. Metricas en {CSV_PATH}")


if __name__ == "__main__":
    main()
