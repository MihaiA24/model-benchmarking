from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from model_benchmark.declarations.canonical import canonical_json_bytes
from model_benchmark.runtime.campaign_budget import (
    CampaignBudgetError,
    campaign_status,
)
from model_benchmark.runtime.functional_v1 import FunctionalV1HomeError

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_HOME = _PROJECT_ROOT / ".model-benchmark-paid-campaign"
_DEFAULT_QUALIFICATION = (
    _PROJECT_ROOT
    / "artifacts"
    / "qualification"
    / "functional-v1"
    / "dry-launch-qualification.json"
)


def _emit(value: dict[str, object]) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(value) + b"\n")
    sys.stdout.buffer.flush()


def _status(home: Path, qualification: Path) -> dict[str, object]:
    return campaign_status(
        project_root=_PROJECT_ROOT,
        home_path=home,
        qualification_path=qualification,
    )


def _blocked(error: BaseException) -> int:
    _emit(
        {
            "action": "blocked",
            "message": str(error),
            "reason_code": "campaign-state-invalid",
        }
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fixed DeepSeek, Hy3, MiniMax M3 Campaign with a sealed "
            "$25 worst-case gate"
        )
    )
    parser.add_argument("--home", default=_DEFAULT_HOME, type=Path)
    parser.add_argument("--qualification", default=_DEFAULT_QUALIFICATION, type=Path)
    parser.add_argument("--env-file", default=_PROJECT_ROOT / ".env", type=Path)
    parser.add_argument(
        "--approve-infrastructure-retry",
        metavar="FAILED_RUN_ID",
        help="start one replacement Run after reviewing an infrastructure failure",
    )
    arguments = parser.parse_args(argv)
    home = arguments.home.resolve(strict=False)
    qualification = arguments.qualification.resolve()
    env_file = arguments.env_file.resolve()
    retry_approval = arguments.approve_infrastructure_retry

    try:
        status = _status(home, qualification)
    except (CampaignBudgetError, FunctionalV1HomeError, OSError, ValueError) as error:
        return _blocked(error)

    while True:
        _emit(status)
        action = status["action"]
        if action == "complete":
            return 0
        if action == "blocked":
            return 3
        if action == "retry":
            if retry_approval != status.get("failed_run_id"):
                return 3
            retry_approval = None
            action = "start"
        elif retry_approval is not None:
            return _blocked(ValueError("infrastructure retry approval is stale"))
        if action not in {"start", "resume"}:
            return _blocked(ValueError(f"unsupported Campaign action: {action}"))

        manifest = str(status["manifest"])
        environment = dict(os.environ)
        environment.update(
            {
                "MODEL_BENCHMARK_ENV_FILE": str(env_file),
                "MODEL_BENCHMARK_HOME": str(home),
                "MODEL_BENCHMARK_MANIFEST": str(_PROJECT_ROOT / manifest),
            }
        )
        command = [str(_PROJECT_ROOT / "scripts" / "run-functional-v1")]
        if action == "resume":
            command.extend(["--resume", str(status["run_id"])])
        completed = subprocess.run(
            command,
            cwd=_PROJECT_ROOT,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode

        previous = status
        try:
            status = _status(home, qualification)
        except (
            CampaignBudgetError,
            FunctionalV1HomeError,
            OSError,
            ValueError,
        ) as error:
            return _blocked(error)
        if (
            status.get("action") == previous.get("action")
            and status.get("manifest") == previous.get("manifest")
            and status.get("run_id") == previous.get("run_id")
            and status.get("completed_runs") == previous.get("completed_runs")
        ):
            return _blocked(
                RuntimeError("successful runner invocation made no Campaign progress")
            )


if __name__ == "__main__":
    raise SystemExit(main())
