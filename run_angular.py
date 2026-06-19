#!/usr/bin/env python3
"""Harness Angular (Angular 21 + Vitest). Verificacion: npm run build (build-only)."""
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
BASELINE = pathlib.Path("baselines/angular-conduit").resolve()

# seed_patches: {rel_path: (old_str, new_str)}  — aplicado ANTES de enviar al modelo
# new_files:    {rel_path: content}              — ficheros extra (tests, stubs)
TASKS = [
    {
        "name": "ng-bug1-missing-input",
        "target_file": "src/app/features/article/components/article-list.component.ts",
        "seed_patches": {
            "src/app/features/article/components/article-list.component.ts": (
                "  @Input() limit!: number;\n  @Input() config!: ArticleListConfig;",
                "  @Input() limit!: number;\n  config!: ArticleListConfig;"
            )
        },
        "new_files": {},
        "prompt": (
            "Bug report: the Angular build fails with a template binding error. "
            "The @Input() decorator was accidentally removed from the 'config' property "
            "in ArticleListComponent, so Angular's strict template checking rejects "
            "the [config]=\"...\" binding in the parent template.\n\n"
            "Fix the component by restoring the missing @Input() decorator on the 'config' property. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "build_cmd": ["npm", "run", "build"],
        "test_ok_equals_build": True,
    },
    {
        "name": "ng-feat1-reading-time",
        "target_file": "src/app/features/article/components/article-preview.component.ts",
        "seed_patches": {
            "src/app/features/article/components/article-preview.component.ts": (
                "        <span>Read more...</span>",
                "        <span>Read more...</span>\n"
                "        <span class=\"reading-time\">{{ getReadingTime(article().body) }} min read</span>"
            )
        },
        "new_files": {},
        "prompt": (
            "Feature request: add a reading time estimate to the article preview. "
            "The template already calls getReadingTime(article().body) but the method "
            "does not exist in the component class, causing a TypeScript build error.\n\n"
            "Implement getReadingTime(body: string): number in the component class:\n"
            "- Count words by splitting on whitespace\n"
            "- Divide by 200 (average reading speed wpm)\n"
            "- Return minimum 1\n\n"
            "Follow Angular 21 best practices (signals, ChangeDetectionStrategy.OnPush). "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "build_cmd": ["npm", "run", "build"],
        "test_ok_equals_build": True,
    },
    {
        "name": "ng-feat2-service-search",
        "target_file": "src/app/features/article/services/articles.service.ts",
        "seed_patches": {
            "src/app/features/article/services/articles.service.ts": (
                "@Injectable({ providedIn: 'root' })\nexport class ArticlesService {",
                "interface ArticlesRepository {\n"
                "  query(config: ArticleListConfig): Observable<{ articles: Article[]; articlesCount: number }>;\n"
                "  get(slug: string): Observable<Article>;\n"
                "  delete(slug: string): Observable<void>;\n"
                "  create(article: Partial<Article>): Observable<Article>;\n"
                "  update(article: Partial<Article>): Observable<Article>;\n"
                "  favorite(slug: string): Observable<Article>;\n"
                "  unfavorite(slug: string): Observable<void>;\n"
                "  search(query: string): Observable<Article[]>;\n"
                "}\n\n"
                "@Injectable({ providedIn: 'root' })\n"
                "export class ArticlesService implements ArticlesRepository {"
            )
        },
        "new_files": {},
        "prompt": (
            "Feature request: implement the search() method in ArticlesService. "
            "The service now declares it implements ArticlesRepository, but the search() "
            "method is missing, causing a TypeScript compilation error.\n\n"
            "Implement search(query: string): Observable<Article[]> that:\n"
            "- Calls GET /articles with query param 'q' set to the query string\n"
            "- Returns the articles array from the response\n"
            "- Uses the same HttpClient patterns already used in the service\n\n"
            "Follow Angular 21 and RxJS best practices. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "build_cmd": ["npm", "run", "build"],
        "test_ok_equals_build": True,
    },
]

RESULTS = pathlib.Path("results")
RESULTS.mkdir(exist_ok=True)
CSV_PATH = RESULTS / "metrics_angular.csv"


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


def make_workdir(workdir: pathlib.Path):
    """Copia baseline sin node_modules/.git/dist y crea junction a node_modules."""
    ignore = shutil.ignore_patterns("node_modules", ".git", "dist", "*.pack", "*.idx", "*.rev")
    shutil.copytree(BASELINE, workdir, ignore=ignore)
    # Junction (Windows) — no requiere permisos de admin
    nm_src = str(BASELINE / "node_modules")
    nm_dst = str(workdir / "node_modules")
    subprocess.run(["cmd", "/c", "mklink", "/J", nm_dst, nm_src],
                   check=True, capture_output=True)


def apply_patches(workdir, seed_patches, new_files):
    for rel, (old, new) in seed_patches.items():
        p = workdir / rel
        content = p.read_text(encoding="utf-8")
        if old not in content:
            raise ValueError(f"Patch string not found in {rel}")
        p.write_text(content.replace(old, new, 1), encoding="utf-8")
    for rel, content in new_files.items():
        p = workdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def run_build(workdir):
    p = subprocess.run("npm run build", cwd=workdir, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", shell=True)
    return p.returncode == 0


def main():
    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["task", "model", "run", "build_ok", "test_ok",
                        "in_tok", "out_tok", "cost_usd", "latency_s", "workdir"])
        for task in TASKS:
            for model in MODELS:
                for run in range(1, RUNS + 1):
                    label = f"{task['name']}__{model.replace('/', '_')}__r{run}"
                    workdir = RESULTS / label
                    try:
                        if workdir.exists():
                            shutil.rmtree(workdir, onerror=_force_remove)
                        make_workdir(workdir)
                        apply_patches(workdir, task["seed_patches"], task["new_files"])
                        target = workdir / task["target_file"]
                        text, usage, latency = call_model(model, target.read_text(encoding="utf-8"), task["prompt"])
                        target.write_text(extract_code(text), encoding="utf-8")
                        build_ok = run_build(workdir)
                        # Angular: build-only, test_ok = build_ok
                        test_ok = build_ok
                        it = usage.get("prompt_tokens", 0); ot = usage.get("completion_tokens", 0)
                        pin, pout = PRICES.get(model, (0, 0))
                        cost = it / 1e6 * pin + ot / 1e6 * pout
                        (workdir / "_raw_response.txt").write_text(text, encoding="utf-8")
                        w.writerow([task["name"], model, run, build_ok, test_ok,
                                    it, ot, round(cost, 4), round(latency, 1), str(workdir)])
                        print(f"{task['name']:28} | {model:32} | run {run} -> "
                              f"build={build_ok} ${cost:.4f}")
                    except Exception as e:
                        w.writerow([task["name"], model, run, "ERROR", "ERROR", 0, 0, 0, 0, str(e)[:200]])
                        print(f"{task['name']:28} | {model:32} | run {run} -> ERROR: {e}")
    print(f"\nListo. Metricas en {CSV_PATH}")


if __name__ == "__main__":
    main()
