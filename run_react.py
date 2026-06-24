#!/usr/bin/env python3
"""Harness React (CRA 1.x + Redux). Verificacion: Jest tests."""
import time, shutil, subprocess, csv, pathlib, re, requests, stat, os

KEY_FILE = pathlib.Path("openrouter_key.txt")
OPENROUTER_API_KEY = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "PEGA_AQUI_TU_KEY":
    raise SystemExit("Falta la API key en openrouter_key.txt")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = [
    # Originales ya evaluados (sus filas ya estan en los CSV) -> NO re-ejecutar.
    # "minimax/minimax-m3",
    # "deepseek/deepseek-v4-flash",
    # "z-ai/glm-4.7",
    "qwen/qwen3.7-plus",
    "google/gemini-3.1-flash-lite",
    "qwen/qwen3-coder-next",
    "tencent/hy3-preview",
    "qwen/qwen3-coder",          # Qwen3 Coder 480B A35B
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
    "minimax/minimax-m2.7",      # MiniMax M2.7 (m3 ya evaluado)
]
PRICES = {
    "minimax/minimax-m3":              (0.30, 1.20),
    "deepseek/deepseek-v4-flash":      (0.09, 0.18),
    "z-ai/glm-4.7":                    (0.40, 1.75),
    "qwen/qwen3.7-plus":               (0.32, 1.28),
    "google/gemini-3.1-flash-lite":    (0.25, 1.50),
    "qwen/qwen3-coder-next":           (0.11, 0.80),
    "tencent/hy3-preview":             (0.066, 0.26),
    "qwen/qwen3-coder":                (0.22, 1.80),
    "deepseek/deepseek-v4-pro":        (0.435, 0.87),
    "z-ai/glm-5.2":                    (1.00, 4.00),
    "minimax/minimax-m2.7":            (0.25, 1.00),
}
RUNS = 3
BASELINE = pathlib.Path("baselines/react-conduit").resolve()

BUG1_TEST = """\
import reducer from './articleList';
import { ARTICLE_FAVORITED } from '../constants/actionTypes';

test('ARTICLE_FAVORITED debe actualizar favoritesCount', () => {
  const state = {
    articles: [{ slug: 'test-slug', favorited: false, favoritesCount: 5 }]
  };
  const action = {
    type: ARTICLE_FAVORITED,
    payload: { article: { slug: 'test-slug', favorited: true, favoritesCount: 6 } }
  };
  const result = reducer(state, action);
  expect(result.articles[0].favorited).toBe(true);
  expect(result.articles[0].favoritesCount).toBe(6);
});
"""

FEAT1_STUB = """\
/**
 * Calcula el tiempo de lectura estimado en minutos.
 * @param {string} body - Texto del artículo
 * @returns {number} Minutos de lectura (mínimo 1)
 */
export default function getReadingTime(body) {
  // TODO: implementar
  return 0;
}
"""

FEAT1_TEST = """\
import getReadingTime from './readingTime';

test('devuelve 1 para texto vacío o muy corto', () => {
  expect(getReadingTime('')).toBe(1);
  expect(getReadingTime('hola')).toBe(1);
});

test('devuelve 1 para exactamente 200 palabras', () => {
  const body = Array(200).fill('palabra').join(' ');
  expect(getReadingTime(body)).toBe(1);
});

test('devuelve 2 para 400 palabras', () => {
  const body = Array(400).fill('palabra').join(' ');
  expect(getReadingTime(body)).toBe(2);
});

test('devuelve 3 para 600 palabras', () => {
  const body = Array(600).fill('palabra').join(' ');
  expect(getReadingTime(body)).toBe(3);
});
"""

FEAT2_TEST = """\
import reducer from './articleList';

test('FILTER_BY_AUTHOR filtra artículos por username del autor', () => {
  const state = {
    articles: [
      { slug: 'a', author: { username: 'alice' }, title: 'A', favorited: false, favoritesCount: 0 },
      { slug: 'b', author: { username: 'bob' },   title: 'B', favorited: false, favoritesCount: 0 },
      { slug: 'c', author: { username: 'alice' }, title: 'C', favorited: false, favoritesCount: 0 }
    ]
  };
  const action = { type: 'FILTER_BY_AUTHOR', author: 'alice' };
  const result = reducer(state, action);
  expect(result.articles).toHaveLength(2);
  expect(result.articles.every(a => a.author.username === 'alice')).toBe(true);
  expect(result.filteredByAuthor).toBe('alice');
});
"""

TASKS = [
    {
        "name": "re-bug1-favorite-count",
        "target_file": "src/reducers/articleList.js",
        "seed_patches": {
            "src/reducers/articleList.js": (
                "              favorited: action.payload.article.favorited,\n"
                "              favoritesCount: action.payload.article.favoritesCount",
                "              favorited: action.payload.article.favorited"
            )
        },
        "new_files": {
            "src/reducers/articleList.test.js": BUG1_TEST,
        },
        "prompt": (
            "Bug report: in the Redux reducer, the ARTICLE_FAVORITED action updates "
            "the 'favorited' flag but does NOT update 'favoritesCount'. "
            "As a result, the favorite counter displayed in the UI never changes.\n\n"
            "The following test must pass:\n"
            "  expect(result.articles[0].favoritesCount).toBe(6)  // was 5, favorited → true\n\n"
            "Fix the reducer so that both 'favorited' and 'favoritesCount' are updated "
            "from action.payload.article. Respect the existing code style. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "test_pattern": "articleList.test",
    },
    {
        "name": "re-feat1-reading-time",
        "target_file": "src/utils/readingTime.js",
        "seed_patches": {},
        "new_files": {
            "src/utils/readingTime.js": FEAT1_STUB,
            "src/utils/readingTime.test.js": FEAT1_TEST,
        },
        "prompt": (
            "Feature request: implement the getReadingTime(body) function so all tests pass.\n\n"
            "Requirements:\n"
            "- Count words by splitting the body string on whitespace\n"
            "- Divide word count by 200 (average reading speed in wpm)\n"
            "- Use Math.ceil and return minimum 1\n"
            "- Handle empty string or null body (return 1)\n\n"
            "The function is exported as default. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "test_pattern": "readingTime.test",
    },
    {
        "name": "re-feat2-author-filter",
        "target_file": "src/reducers/articleList.js",
        "seed_patches": {},
        "new_files": {
            "src/reducers/articleListFilter.test.js": FEAT2_TEST,
        },
        "prompt": (
            "Feature request: add a FILTER_BY_AUTHOR case to the articleList reducer.\n\n"
            "The new action has shape: { type: 'FILTER_BY_AUTHOR', author: string }\n\n"
            "The reducer must:\n"
            "- Filter state.articles to only those where article.author.username === action.author\n"
            "- Set state.filteredByAuthor = action.author\n"
            "- Keep all other state fields unchanged\n\n"
            "The following test must pass:\n"
            "  const result = reducer(state, { type: 'FILTER_BY_AUTHOR', author: 'alice' });\n"
            "  expect(result.articles).toHaveLength(2);\n"
            "  expect(result.filteredByAuthor).toBe('alice');\n\n"
            "Respect the existing Redux reducer style. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        "test_pattern": "articleListFilter.test",
    },
]

RESULTS = pathlib.Path("results")
RESULTS.mkdir(exist_ok=True)
CSV_PATH = RESULTS / "metrics_react.csv"


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
    """Copia baseline sin node_modules/.git/build y crea junction a node_modules."""
    ignore = shutil.ignore_patterns("node_modules", ".git", "build", "*.pack", "*.idx", "*.rev")
    shutil.copytree(BASELINE, workdir, ignore=ignore)
    nm_src = str(BASELINE / "node_modules")
    nm_dst = str(workdir / "node_modules")
    subprocess.run(["cmd", "/c", "mklink", "/J", nm_dst, nm_src],
                   check=True, capture_output=True)


def apply_patches(workdir, seed_patches, new_files):
    for rel, (old, new) in seed_patches.items():
        p = workdir / rel
        content = p.read_text(encoding="utf-8")
        if old not in content:
            raise ValueError(f"Patch string not found in {rel}: '{old[:60]}...'")
        p.write_text(content.replace(old, new, 1), encoding="utf-8")
    for rel, content in new_files.items():
        p = workdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def run_checks(workdir, task):
    env = {**os.environ, "CI": "true"}
    build_p = subprocess.run("npm run build", cwd=workdir, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", shell=True, env=env)
    build_ok = build_p.returncode == 0

    test_cmd = f"npm test -- --watchAll=false --testPathPattern={task['test_pattern']}"
    test_p = subprocess.run(test_cmd, cwd=workdir, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", shell=True, env=env)
    test_ok = test_p.returncode == 0
    return build_ok, test_ok


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
                        build_ok, test_ok = run_checks(workdir, task)
                        it = usage.get("prompt_tokens", 0); ot = usage.get("completion_tokens", 0)
                        pin, pout = PRICES.get(model, (0, 0))
                        cost = it / 1e6 * pin + ot / 1e6 * pout
                        (workdir / "_raw_response.txt").write_text(text, encoding="utf-8")
                        w.writerow([task["name"], model, run, build_ok, test_ok,
                                    it, ot, round(cost, 4), round(latency, 1), str(workdir)])
                        print(f"{task['name']:28} | {model:32} | run {run} -> "
                              f"build={build_ok} test={test_ok} ${cost:.4f}")
                    except Exception as e:
                        w.writerow([task["name"], model, run, "ERROR", "ERROR", 0, 0, 0, 0, str(e)[:200]])
                        print(f"{task['name']:28} | {model:32} | run {run} -> ERROR: {e}")
    print(f"\nListo. Metricas en {CSV_PATH}")


if __name__ == "__main__":
    main()
