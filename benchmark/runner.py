"""Unified benchmark runner."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from benchmark.adapters import ADAPTERS, ALL_HARNESSES
from benchmark.checks import run_checks
from benchmark.models import expand_models
from benchmark.prompts import agent_prompt, raw_api_prompt
from benchmark.tasks import STACK_CSV, STACKS, TASK_BY_NAME, TASKS_BY_STACK
from benchmark.util import benchmark_env, repo_path, safe_label, secret_file
from benchmark.workdir import make_workdir

FIELDNAMES = [
    "harness",
    "task",
    "model",
    "run",
    "capability_mode",
    "telemetry_trust",
    "tool_set",
    "build_ok",
    "test_ok",
    "in_tok",
    "out_tok",
    "cost_usd",
    "model_calls",
    "telemetry_note",
    "latency_s",
    "workdir",
    "transcript_path",
    "error",
]

_SKIP_DIRS = {".git", "node_modules", "target", "dist", "build", "__pycache__"}
_ARTIFACT_FILES = {"_raw_response.txt", "_error.txt", "_build_output.txt", "_test_output.txt"}
_MAX_CAPTURE_BYTES = 250_000
_CLI_HARNESSES = {"omp": "omp", "opencode": "opencode", "hermes": "hermes"}


def _csv_path(stack: str, results_dir: Path) -> Path:
    return results_dir / STACK_CSV[stack].name
def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {field: row.get(field, "") for field in FIELDNAMES}
    normalized["harness"] = normalized["harness"] or "raw_api"
    if not normalized["transcript_path"] and normalized.get("workdir"):
        normalized["transcript_path"] = str(Path(normalized["workdir"]) / "_raw_response.txt")
    if not normalized["capability_mode"]:
        normalized["capability_mode"] = "single_shot" if normalized["harness"] == "raw_api" else "agent_iterated"
    if not normalized["telemetry_trust"]:
        normalized["telemetry_trust"] = {"raw_api": "exact", "omp": "parsed", "opencode": "parsed", "hermes": "blank"}.get(normalized["harness"], "")
    if not normalized["tool_set"] and normalized["harness"] == "omp":
        normalized["tool_set"] = "read,bash,edit,write,grep,find,lsp"
    if not normalized["tool_set"] and normalized["harness"] == "hermes":
        normalized["tool_set"] = "terminal,file"
    if not normalized["model_calls"] and normalized["harness"] == "raw_api" and normalized.get("test_ok") not in ("", "ERROR", None):
        normalized["model_calls"] = "1"
        normalized["telemetry_note"] = normalized["telemetry_note"] or "legacy raw_api row; one OpenRouter request"
    return normalized


def csv_schema_matches(path: Path) -> bool:
    if not path.exists():
        return True
    with open(path, newline="", encoding="utf-8") as f:
        return (csv.DictReader(f).fieldnames or []) == FIELDNAMES


def migrate_csv_schema(path: Path) -> bool:
    """Rewrite one metrics CSV to the current schema. Returns True if changed."""
    if not path.exists():
        return False
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_fields = reader.fieldnames or []
        rows = [_normalize_row(row) for row in reader]
    if old_fields == FIELDNAMES:
        return False
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return True


def require_csv_schema(path: Path) -> None:
    if not csv_schema_matches(path):
        raise RuntimeError(f"CSV schema mismatch in {path}; run `python run_benchmark.py --migrate-csv --stack ...` first")


def load_done(path: Path) -> set[tuple[str, str, str, str]]:
    if not path.exists():
        return set()
    done: set[tuple[str, str, str, str]] = set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = _normalize_row(row)
            if row.get("test_ok") not in ("", "ERROR", None):
                done.add((row["harness"], row["task"], row["model"], str(row["run"])))
    return done


def append_row(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require_csv_schema(path)
    write_header = not path.exists()
    normalized = {field: row.get(field, "") for field in FIELDNAMES}
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(normalized)


def parse_csv_arg(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def expand_harnesses(value: str) -> list[str]:
    requested = parse_csv_arg(value)
    if not requested or "all" in requested:
        return list(ALL_HARNESSES)
    expanded: list[str] = []
    for item in requested:
        if item == "agent":
            expanded.extend(["omp", "opencode", "hermes"])
        else:
            expanded.append(item)
    unknown = sorted(set(expanded) - set(ALL_HARNESSES))
    if unknown:
        raise SystemExit(f"Harness desconocido: {', '.join(unknown)}")
    return list(dict.fromkeys(expanded))


def expand_stacks(value: str) -> list[str]:
    requested = parse_csv_arg(value)
    if not requested or "all" in requested:
        return list(STACKS)
    unknown = sorted(set(requested) - set(STACKS))
    if unknown:
        raise SystemExit(f"Stack desconocido: {', '.join(unknown)}")
    return requested


def parse_adapter_models(values: list[str] | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise SystemExit("--adapter-model debe tener formato harness=model_selector")
        harness, selector = value.split("=", 1)
        harness = harness.strip()
        selector = selector.strip()
        if harness not in ALL_HARNESSES:
            raise SystemExit(f"Harness desconocido en --adapter-model: {harness}")
        if not selector:
            raise SystemExit(f"Selector vacio para --adapter-model {harness}")
        mapping[harness] = selector
    return mapping


def select_tasks(stacks: Iterable[str], task_names: list[str] | None) -> list:
    if task_names:
        selected = []
        for name in task_names:
            if name not in TASK_BY_NAME:
                raise SystemExit(f"Tarea desconocida: {name}")
            selected.append(TASK_BY_NAME[name])
        stack_set = set(stacks)
        return [task for task in selected if task.stack in stack_set]
    tasks = []
    for stack in stacks:
        tasks.extend(TASKS_BY_STACK[stack])
    return tasks


def _validate_model_for_harness(harness: str, model: str, adapter_model: str, overridden: bool) -> list[str]:
    errors: list[str] = []
    if "/" not in adapter_model:
        errors.append(f"{harness}: model selector must be provider/model, got `{adapter_model}`")
    if harness == "raw_api" and adapter_model.startswith("opencode-go/"):
        errors.append("raw_api cannot call OpenCode Go subscription models; use `--harness agent` or override raw_api to an OpenRouter slug")
    return errors


def validate_plan(planned: list[tuple]) -> list[str]:
    errors: list[str] = []
    for task, _, harness, model, adapter_model, _, overridden in planned:
        errors.extend(_validate_model_for_harness(harness, model, adapter_model, overridden))
    return sorted(set(errors))


def _snapshot_files(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_dir() or path.is_symlink() or path.name in _ARTIFACT_FILES:
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        snapshot[rel] = hashlib.sha256(data).hexdigest()
    return snapshot


def _changed_files(root: Path, before: dict[str, str]) -> list[str]:
    after = _snapshot_files(root)
    changed = sorted(rel for rel, digest in after.items() if before.get(rel) != digest)
    removed = sorted(rel for rel in before if rel not in after)
    return changed + [f"{rel} (deleted)" for rel in removed]


def _append_agent_submission(transcript_path: Path, workdir: Path, before: dict[str, str]) -> None:
    changed = _changed_files(workdir, before)
    with open(transcript_path, "a", encoding="utf-8") as f:
        f.write("\n\n=== CHANGED FILES ===\n")
        if not changed:
            f.write("(none)\n")
            return
        for rel in changed:
            f.write(f"\n--- {rel} ---\n")
            if rel.endswith(" (deleted)"):
                continue
            path = workdir / rel
            try:
                data = path.read_bytes()
            except OSError as exc:
                f.write(f"[unreadable: {exc}]\n")
                continue
            if len(data) > _MAX_CAPTURE_BYTES:
                f.write(f"[skipped: {len(data)} bytes]\n")
                continue
            try:
                f.write(data.decode("utf-8"))
            except UnicodeDecodeError:
                f.write(f"[binary: {len(data)} bytes]\n")
            if not data.endswith(b"\n"):
                f.write("\n")


def run_one(*, harness: str, task, model: str, adapter_model: str, run: int, results_dir: Path, adapter_timeout_s: int, check_timeout_s: int, workdir_cache_dir: Path | None = None) -> dict[str, object]:
    label = safe_label(f"{harness}__{task.name}__{model}__r{run}")
    workdir = results_dir / label
    transcript_path = workdir / "_raw_response.txt"
    row: dict[str, object] = {
        "harness": harness,
        "task": task.name,
        "model": model,
        "run": run,
        "workdir": str(workdir),
        "transcript_path": str(transcript_path),
    }
    before: dict[str, str] = {}
    try:
        make_workdir(task, workdir, cache_dir=workdir_cache_dir)
        before = _snapshot_files(workdir)
        prompt = raw_api_prompt(task) if harness == "raw_api" else agent_prompt(task)
        adapter = ADAPTERS[harness]()
        result = adapter.run(
            task=task,
            workdir=workdir,
            model=adapter_model,
            prompt=prompt,
            transcript_path=transcript_path,
            timeout_s=adapter_timeout_s,
        )
        if harness != "raw_api":
            _append_agent_submission(transcript_path, workdir, before)
        build_ok, test_ok = run_checks(workdir, task, timeout_s=check_timeout_s)
        row.update({
            "build_ok": build_ok,
            "test_ok": test_ok,
            "capability_mode": result.capability_mode,
            "telemetry_trust": result.telemetry_trust,
            "tool_set": result.tool_set,
            "in_tok": result.in_tokens,
            "out_tok": result.out_tokens,
            "cost_usd": result.cost_usd,
            "model_calls": result.model_calls,
            "telemetry_note": result.telemetry_note,
            "latency_s": round(result.latency_s, 1),
            "error": "",
        })
    except Exception as exc:
        if workdir.exists():
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "_error.txt").write_text(str(exc), encoding="utf-8")
            if harness != "raw_api" and transcript_path.exists() and before:
                _append_agent_submission(transcript_path, workdir, before)
        row.update({
            "build_ok": "ERROR",
            "test_ok": "ERROR",
            "capability_mode": "single_shot" if harness == "raw_api" else "agent_iterated",
            "telemetry_trust": {"raw_api": "exact", "omp": "parsed", "opencode": "parsed", "hermes": "blank"}.get(harness, ""),
            "tool_set": {"omp": "read,bash,edit,write,grep,find,lsp", "hermes": "terminal,file"}.get(harness, ""),
            "in_tok": "",
            "out_tok": "",
            "cost_usd": "",
            "model_calls": "",
            "telemetry_note": "",
            "latency_s": "",
            "error": str(exc)[:500],
        })
    return row


def _has_secret(env_name: str, filename: str) -> bool:
    env = benchmark_env()
    return bool(env.get(env_name)) or secret_file(filename).exists()


def _has_opencode_go_secret() -> bool:
    env = benchmark_env()
    return (
        bool(env.get("OPENCODE_API_KEY"))
        or bool(env.get("OPENCODE_GO_API_KEY"))
        or secret_file("opencode_key.txt").exists()
    )


def _opencode_models() -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["opencode", "models"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=benchmark_env(),
        )
    except Exception as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _check_seeded_bug(task, baseline: Path) -> str | None:
    """Assert the seeded bug is present in the baseline before running."""
    if not task.seed_patches:
        target = baseline / task.target_file
        if not target.exists():
            return None
        content = target.read_text(encoding="utf-8", errors="replace")
        if task.name == "bug1-petvalidator" and "hasLength" not in content:
            return f"bug1-petvalidator: expected 'hasLength' bug in {task.target_file} — baseline may have drifted"
        if task.name == "bug2-ownercontroller" and ">= 1" not in content:
            return f"bug2-ownercontroller: expected '>= 1' bug in {task.target_file} — baseline may have drifted"
    return None

def run_preflight(*, planned: list[tuple], stacks: list[str], tasks: list, results_dir: Path) -> int:
    failures: list[str] = []
    warnings: list[str] = []
    harnesses = sorted({item[2] for item in planned})
    adapter_models = [item[4] for item in planned]

    for harness in harnesses:
        binary = _CLI_HARNESSES.get(harness)
        if binary and not shutil.which(binary):
            failures.append(f"missing CLI binary: {binary}")

    if "raw_api" in harnesses and not _has_secret("OPENROUTER_API_KEY", "openrouter_key.txt"):
        failures.append("missing OpenRouter key: set OPENROUTER_API_KEY or create openrouter_key.txt")
    if any(adapter_model.startswith("opencode-go/") for *_, adapter_model, _, _ in planned):
        if not _has_opencode_go_secret():
            failures.append("missing OpenCode Go key: set OPENCODE_API_KEY / OPENCODE_GO_API_KEY or create opencode_key.txt")
        if shutil.which("opencode"):
            code, output = _opencode_models()
            if code != 0:
                warnings.append(f"opencode models failed: {output[:200]}")
            else:
                missing = sorted({model for model in adapter_models if model.startswith("opencode-go/") and model not in output})
                if missing:
                    warnings.append("OpenCode did not list requested Go models: " + ", ".join(missing[:5]))

    for task in tasks:
        baseline = repo_path(task.baseline)
        if not baseline.exists():
            failures.append(f"missing baseline for {task.name}: {baseline}")
        if task.link_node_modules and not (baseline / "node_modules").exists():
            failures.append(f"missing node_modules for {task.name}: {baseline / 'node_modules'}")
        bug_check = _check_seeded_bug(task, baseline)
        if bug_check:
            failures.append(bug_check)

    for stack in stacks:
        csv_path = _csv_path(stack, results_dir)
        if not csv_schema_matches(csv_path):
            failures.append(f"legacy CSV schema: {csv_path}; run --migrate-csv")

    failures.extend(validate_plan(planned))

    for line in warnings:
        print(f"WARN: {line}")
    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1
    print(f"Preflight OK: {len(planned)} planned runs")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run raw API and agent-harness benchmark tasks.")
    parser.add_argument("--stack", default="all", help="Comma-separated stacks: springboot,angular,react,data,all")
    parser.add_argument("--task", action="append", help="Run only this task id. Repeatable.")
    parser.add_argument("--harness", default="raw_api", help="Comma-separated harnesses: raw_api,omp,opencode,hermes,agent,all")
    parser.add_argument("--models", help="Comma-separated models or preset: original,new,opencode-go,all. Defaults to BENCHMARK_MODELS from .env/env, then new.")
    parser.add_argument("--adapter-model", action="append", help="Override selector per harness, e.g. omp=openrouter/qwen/qwen3.7-plus")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--workdir-cache", help="Seeded task snapshot cache path. Defaults to BENCHMARK_WORKDIR_CACHE from .env/env.")
    parser.add_argument("--adapter-timeout", type=int, default=900, help="Seconds for API/agent invocation")
    parser.add_argument("--check-timeout", type=int, default=600, help="Seconds for each build/test command")
    parser.add_argument("--no-resume", action="store_true", help="Do not skip completed rows already in CSV")
    parser.add_argument("--preflight", action="store_true", help="Validate setup and planned runs without invoking harnesses")
    parser.add_argument("--migrate-csv", action="store_true", help="Rewrite selected metrics CSVs to the current schema and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without copying baselines or invoking harnesses")
    return parser



def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = benchmark_env()
    harnesses = expand_harnesses(args.harness)
    stacks = expand_stacks(args.stack)
    models = expand_models(args.models or env.get("BENCHMARK_MODELS"))
    adapter_models = parse_adapter_models(args.adapter_model)
    tasks = select_tasks(stacks, args.task)
    results_dir = repo_path(args.results_dir)
    workdir_cache = args.workdir_cache or env.get("BENCHMARK_WORKDIR_CACHE")
    workdir_cache_dir = repo_path(workdir_cache) if workdir_cache else None

    if args.migrate_csv:
        changed = []
        for stack in stacks:
            csv_path = _csv_path(stack, results_dir)
            if migrate_csv_schema(csv_path):
                changed.append(str(csv_path))
        print("Migrated CSVs:" if changed else "No CSV migration needed.")
        for path in changed:
            print(f"  {path}")
        return 0

    planned = []
    for task in tasks:
        csv_path = _csv_path(task.stack, results_dir)
        done = set() if args.no_resume else load_done(csv_path)
        for harness in harnesses:
            for model in models:
                overridden = harness in adapter_models
                adapter_model = adapter_models.get(harness, model)
                for run in range(1, args.runs + 1):
                    key = (harness, task.name, model, str(run))
                    if key in done:
                        print(f"{task.name:32} | {harness:8} | {model:32} | run {run} -> SKIP")
                        continue
                    planned.append((task, csv_path, harness, model, adapter_model, run, overridden))

    validation_errors = validate_plan(planned)
    if validation_errors:
        for error in validation_errors:
            print(f"FAIL: {error}")
        return 2

    if args.preflight:
        return run_preflight(planned=planned, stacks=stacks, tasks=tasks, results_dir=results_dir)

    if args.dry_run:
        for task, _, harness, model, adapter_model, run, _ in planned:
            print(f"PLAN {task.stack:10} | {task.name:32} | {harness:8} | model={model} | adapter_model={adapter_model} | run={run}")
        print(f"Planned runs: {len(planned)}")
        return 0

    for stack in stacks:
        require_csv_schema(_csv_path(stack, results_dir))

    for task, csv_path, harness, model, adapter_model, run, _ in planned:
        row = run_one(
            harness=harness,
            task=task,
            model=model,
            adapter_model=adapter_model,
            run=run,
            results_dir=results_dir,
            adapter_timeout_s=args.adapter_timeout,
            check_timeout_s=args.check_timeout,
            workdir_cache_dir=workdir_cache_dir,
        )
        append_row(csv_path, row)
        print(
            f"{task.name:32} | {harness:8} | {model:32} | run {run} -> "
            f"build={row.get('build_ok')} test={row.get('test_ok')} cost={row.get('cost_usd', '')} calls={row.get('model_calls', '')}"
        )

    print("\nListo. Ejecuta: python merge_metrics.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
