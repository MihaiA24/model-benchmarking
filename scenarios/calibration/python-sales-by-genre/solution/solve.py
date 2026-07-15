#!/usr/bin/env python3
from pathlib import Path

path = Path("/workspace/repository/sales_by_genre.py")
source = path.read_text(encoding="utf-8")
before = "JOIN InvoiceLine AS il ON il.TrackId = g.GenreId"
after = "JOIN InvoiceLine AS il ON il.TrackId = t.TrackId"
if source.count(before) != 1:
    raise SystemExit("seeded join was not found exactly once")
path.write_text(source.replace(before, after), encoding="utf-8")
