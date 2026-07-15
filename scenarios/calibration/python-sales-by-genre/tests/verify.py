#!/usr/bin/env python3
"""Behavioral verifier for the sales-by-genre calibration scenario."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path


def expected_rows(path: Path) -> list[tuple[str, int]]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    genre_names = {row["GenreId"]: row["Name"] for row in fixture["genres"]}
    track_genres = {row["TrackId"]: row["GenreId"] for row in fixture["tracks"]}
    totals: defaultdict[str, int] = defaultdict(int)
    for row in fixture["invoice_lines"]:
        totals[genre_names[track_genres[row["TrackId"]]]] += row["Quantity"]
    return sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:5]


def execute(input_path: Path, output_path: Path) -> tuple[bool, bytes]:
    completed = subprocess.run(
        [
            "python3",
            "sales_by_genre.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0 or not output_path.is_file():
        return False, b""
    data = output_path.read_bytes()
    try:
        with output_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        actual = [(name, int(quantity)) for name, quantity in rows[1:]]
    except (OSError, UnicodeError, ValueError, csv.Error):
        return False, data
    return rows[:1] == [["Genre", "UnitsSold"]] and actual == expected_rows(input_path), data


def status(value: bool) -> str:
    return "pass" if value else "fail"


def main() -> None:
    agent = Path("data/sales.json")
    hidden = [Path("/tests/data/sales-hidden-a.json"), Path("/tests/data/sales-hidden-b.json")]
    inputs = [agent, *hidden]
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in inputs}
    with tempfile.TemporaryDirectory(prefix="sales-verifier-") as temporary:
        root = Path(temporary)
        acceptance, first = execute(agent, root / "agent.csv")
        _, second = execute(agent, root / "agent-repeat.csv")
        hidden_results = [
            execute(path, root / f"hidden-{index}.csv")[0]
            for index, path in enumerate(hidden)
        ]
    unchanged = all(
        hashlib.sha256(path.read_bytes()).digest() == digest
        for path, digest in before.items()
    )
    regression = first == second and unchanged and first.startswith(b"Genre,UnitsSold\n")
    domain = all(hidden_results)
    task_success = acceptance and regression and domain
    scores = {
        "acceptance_score": int(acceptance),
        "aggregation_correctness": int(domain),
        "regression_score": int(regression),
        "task_success": int(task_success),
    }
    result = {
        "acceptance_score": scores["acceptance_score"],
        "aggregation_correctness": scores["aggregation_correctness"],
        "checks": [
            {
                "evidence": ["data/sales.json", "sales-by-genre.csv"],
                "id": "agent-fixture",
                "status": status(acceptance),
            },
            {
                "evidence": ["sales-by-genre.csv", "input-digests"],
                "id": "report-contract",
                "status": status(regression),
            },
            {
                "evidence": ["tests/data/sales-hidden-a.json", "tests/data/sales-hidden-b.json"],
                "id": "hidden-fixtures",
                "status": status(domain),
            },
        ],
        "domain_scores": {"aggregation_correctness": scores["aggregation_correctness"]},
        "regression_score": scores["regression_score"],
        "required_group_statuses": {
            "agent-fixture": status(acceptance),
            "hidden-fixtures": status(domain),
            "report-contract": status(regression),
        },
        "task_success": task_success,
        "verifier_complete": True,
    }
    output = Path("/logs/verifier")
    output.mkdir(parents=True, exist_ok=True)
    output.joinpath("verifier-result.json").write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    output.joinpath("reward.json").write_text(
        json.dumps(scores, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
