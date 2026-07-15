#!/usr/bin/env python3
"""Generate the deterministic Functional V1 sales fixtures."""

from __future__ import annotations

import json
from pathlib import Path


def fixture(genres: list[str], sales: list[tuple[int, int, int]]) -> dict[str, object]:
    return {
        "genres": [
            {"GenreId": index, "Name": name}
            for index, name in enumerate(genres, start=1)
        ],
        "tracks": [
            {"GenreId": genre_id, "Name": f"Track {track_id}", "TrackId": track_id}
            for track_id, genre_id, _ in sales
        ],
        "invoice_lines": [
            {"InvoiceLineId": index, "Quantity": quantity, "TrackId": track_id}
            for index, (track_id, _, quantity) in enumerate(sales, start=1)
        ],
    }


FIXTURES = {
    "sales-agent.json": fixture(
        ["Rock", "Jazz", "Classical", "Metal", "Blues", "Pop"],
        [
            (101, 1, 6),
            (102, 1, 4),
            (201, 2, 7),
            (301, 3, 5),
            (401, 4, 3),
            (501, 5, 2),
            (601, 6, 1),
        ],
    ),
    "sales-hidden-a.json": fixture(
        ["Ambient", "Folk", "Soul", "Punk", "Disco", "Latin", "Opera"],
        [
            (711, 1, 2),
            (712, 1, 5),
            (721, 2, 7),
            (731, 3, 4),
            (741, 4, 4),
            (751, 5, 3),
            (761, 6, 2),
            (771, 7, 1),
        ],
    ),
    "sales-hidden-b.json": fixture(
        ["Zeta", "Alpha", "Gamma", "Beta", "Delta", "Epsilon"],
        [
            (811, 1, 9),
            (821, 2, 9),
            (831, 3, 8),
            (841, 4, 7),
            (851, 5, 6),
            (861, 6, 5),
        ],
    ),
}


def write_fixture(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for name, value in FIXTURES.items():
        write_fixture(root / "data" / name, value)
        if name == "sales-agent.json":
            write_fixture(root / "seed" / name, value)
        else:
            write_fixture(root / "tests" / "data" / name, value)


if __name__ == "__main__":
    main()
