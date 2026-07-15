#!/usr/bin/env python3
"""Produce the top-selling genres from a schema-compatible sales fixture."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


def top_genres(input_path: Path) -> list[tuple[str, int]]:
    fixture = json.loads(input_path.read_text(encoding="utf-8"))
    database = sqlite3.connect(":memory:")
    try:
        database.executescript(
            """
            CREATE TABLE Genre (GenreId INTEGER PRIMARY KEY, Name TEXT NOT NULL);
            CREATE TABLE Track (TrackId INTEGER PRIMARY KEY, GenreId INTEGER NOT NULL, Name TEXT NOT NULL);
            CREATE TABLE InvoiceLine (InvoiceLineId INTEGER PRIMARY KEY, TrackId INTEGER NOT NULL, Quantity INTEGER NOT NULL);
            """
        )
        database.executemany(
            "INSERT INTO Genre (GenreId, Name) VALUES (:GenreId, :Name)",
            fixture["genres"],
        )
        database.executemany(
            "INSERT INTO Track (TrackId, GenreId, Name) VALUES (:TrackId, :GenreId, :Name)",
            fixture["tracks"],
        )
        database.executemany(
            "INSERT INTO InvoiceLine (InvoiceLineId, TrackId, Quantity) VALUES (:InvoiceLineId, :TrackId, :Quantity)",
            fixture["invoice_lines"],
        )
        return database.execute(
            """
            SELECT g.Name AS Genre, SUM(il.Quantity) AS UnitsSold
            FROM Genre AS g
            JOIN Track AS t ON t.GenreId = g.GenreId
            JOIN InvoiceLine AS il ON il.TrackId = g.GenreId
            GROUP BY g.GenreId, g.Name
            ORDER BY UnitsSold DESC, Genre ASC
            LIMIT 5
            """
        ).fetchall()
    finally:
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/sales.json"))
    parser.add_argument("--output", type=Path, default=Path("sales-by-genre.csv"))
    arguments = parser.parse_args()
    rows = top_genres(arguments.input)
    with arguments.output.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("Genre", "UnitsSold"))
        writer.writerows(rows)


if __name__ == "__main__":
    main()
