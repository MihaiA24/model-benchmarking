#!/usr/bin/env python3
"""Harness Spring Boot — tarea de nueva funcionalidad (feat1)."""
import time, shutil, subprocess, csv, pathlib, re, requests, stat, os

KEY_FILE = pathlib.Path("openrouter_key.txt")
OPENROUTER_API_KEY = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "PEGA_AQUI_TU_KEY":
    raise SystemExit("Falta la API key en openrouter_key.txt")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = [
    "minimax/minimax-m3",
    "deepseek/deepseek-v4-flash",
    "z-ai/glm-4.7",
    "qwen/qwen3.7-plus",
    "google/gemini-3.1-flash-lite",
    "qwen/qwen3-coder-next",
    "tencent/hy3-preview",
    "z-ai/glm-5.2",
]
PRICES = {
    "minimax/minimax-m3":              (0.30, 1.20),
    "deepseek/deepseek-v4-flash":      (0.09, 0.18),
    "z-ai/glm-4.7":                    (0.40, 1.75),
    "qwen/qwen3.7-plus":               (0.32, 1.28),
    "google/gemini-3.1-flash-lite":    (0.25, 1.50),
    "qwen/qwen3-coder-next":           (0.11, 0.80),
    "tencent/hy3-preview":             (0.066, 0.26),
    "z-ai/glm-5.2":                    (1.20, 4.10),
}
RUNS = 3

TASKS = [
    {
        "name": "sb-feat1-name-length",
        "baseline": "baselines/petclinic-feat1",
        "target_file": "src/main/java/org/springframework/samples/petclinic/owner/PetValidator.java",
        "prompt": (
            "Feature request: add validation to PetValidator so that a pet name longer than "
            "50 characters is rejected with error code 'tooLong'. "
            "The following test must pass:\n\n"
            "  void processCreationFormWithTooLongName() {\n"
            "      mockMvc.perform(post(...).param(\"name\", \"A\".repeat(51))\n"
            "          .param(\"type\", \"hamster\").param(\"birthDate\", \"2015-02-12\"))\n"
            "      .andExpect(model().attributeHasFieldErrorCode(\"pet\", \"name\", \"tooLong\"))\n"
            "  }\n\n"
            "Modify ONLY the validate() method in PetValidator. Respect the existing code style. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "build_cmd": ["mvn", "-q", "-DskipTests", "compile"],
        "test_cmd":  ["mvn", "-q", "-Dtest=PetControllerTests#processCreationFormWithTooLongName", "test"],
    },
]

RESULTS = pathlib.Path("results")
RESULTS.mkdir(exist_ok=True)
CSV_PATH = RESULTS / "metrics_springboot.csv"


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
    text = data["choices"][0]["message"]["content"]
    return text, data.get("usage", {}), latency


def extract_code(text):
    m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def _force_remove(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def run_checks(workdir, task):
    out = {}
    for label, cmd in [("build", task["build_cmd"]), ("test", task["test_cmd"])]:
        p = subprocess.run(" ".join(cmd), cwd=workdir, capture_output=True, text=True, shell=True)
        out[label] = (p.returncode == 0)
    return out


def main():
    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["task", "model", "run", "build_ok", "test_ok",
                        "in_tok", "out_tok", "cost_usd", "latency_s", "workdir"])
        for task in TASKS:
            baseline = pathlib.Path(task["baseline"])
            for model in MODELS:
                for run in range(1, RUNS + 1):
                    label = f"{task['name']}__{model.replace('/', '_')}__r{run}"
                    workdir = RESULTS / label
                    try:
                        if workdir.exists():
                            shutil.rmtree(workdir, onerror=_force_remove)
                        shutil.copytree(baseline, workdir,
                                        ignore=shutil.ignore_patterns('target', '.git'))
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
                        print(f"{task['name']:28} | {model:32} | run {run} -> "
                              f"build={checks['build']} test={checks['test']} ${cost:.4f}")
                    except Exception as e:
                        w.writerow([task["name"], model, run, "ERROR", "ERROR", 0, 0, 0, 0, str(e)[:200]])
                        print(f"{task['name']:28} | {model:32} | run {run} -> ERROR: {e}")
    print(f"\nListo. Metricas en {CSV_PATH}")


if __name__ == "__main__":
    main()
