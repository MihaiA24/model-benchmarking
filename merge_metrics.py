#!/usr/bin/env python3
"""Combina todos los metrics CSV en results/metrics_all.csv con modelos anonimizados."""
import pathlib, csv, random, string

RESULTS = pathlib.Path("results")
SOURCES = [
    RESULTS / "metrics.csv",            # Spring Boot bugs (poc_harness.py)
    RESULTS / "metrics_springboot.csv", # Spring Boot feat1
    RESULTS / "metrics_angular.csv",
    RESULTS / "metrics_react.csv",
    RESULTS / "metrics_data.csv",
]
OUT_ALL   = RESULTS / "metrics_all.csv"
OUT_ANON  = RESULTS / "metrics_anon.csv"
OUT_MAP   = RESULTS / "model_mapping.csv"  # NO mostrar hasta el final


def main():
    rows = []
    for src in SOURCES:
        if not src.exists():
            print(f"  SKIP (no existe): {src}")
            continue
        with open(src, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        print(f"  OK: {src.name} ({len(rows)} filas acumuladas)")

    if not rows:
        print("No hay datos que mergear.")
        return

    # Merge completo (con nombres reales)
    fieldnames = list(rows[0].keys())
    with open(OUT_ALL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\nMerge completo: {OUT_ALL} ({len(rows)} filas)")

    # Anonimizacion
    models = sorted({r["model"] for r in rows})
    letters = list(string.ascii_uppercase[:len(models)])
    random.shuffle(letters)
    mapping = {m: f"Modelo {l}" for m, l in zip(models, letters)}

    anon_rows = [{**r, "model": mapping[r["model"]]} for r in rows]
    with open(OUT_ANON, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(anon_rows)
    print(f"Anonimizado:    {OUT_ANON}")

    # Guardar mapping (NO revelar hasta la fase humana)
    with open(OUT_MAP, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias", "model_real"])
        for m, alias in mapping.items():
            w.writerow([alias, m])
    print(f"Mapping guardado en {OUT_MAP} — NO revelar hasta el final de la evaluacion humana")
    print("\nResumen por modelo:")
    for model in models:
        mrs = [r for r in rows if r["model"] == model]
        ok = sum(1 for r in mrs if r.get("test_ok") in ("True", True))
        total = len(mrs)
        costs = [float(r["cost_usd"]) for r in mrs if r.get("cost_usd") not in ("ERROR", "0", 0)]
        avg_cost = sum(costs) / len(costs) if costs else 0
        lats = [float(r["latency_s"]) for r in mrs if r.get("latency_s") not in ("ERROR", "0", 0)]
        avg_lat = sum(lats) / len(lats) if lats else 0
        print(f"  {mapping[model]} ({model}): {ok}/{total} tests ok | "
              f"coste medio ${avg_cost:.4f} | latencia media {avg_lat:.1f}s")


if __name__ == "__main__":
    main()
