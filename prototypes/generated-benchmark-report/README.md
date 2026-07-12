# Generated benchmark report prototype

**Status:** captured throwaway visual prototype for [Prototype the generated benchmark report](https://github.com/MihaiA24/model-benchmarking/issues/22). It tests report structure and visual hierarchy; every displayed result is fictional.

**Accepted direction:** Variant A is the primary report hierarchy. Variant B contributes its publication gate and provenance trace as drill-downs; Variant C contributes its Pareto atlas as a secondary workload tradeoff view. The final decision is recorded in [`blueprint/generated-benchmark-report.md`](../../blueprint/generated-benchmark-report.md).

## Question

Which static report hierarchy best lets a reader choose a Harness by Workload Family while preserving paired uncertainty, public/private and exact-model strata, dispositions and denominators, operational tradeoffs, and immutable evidence drill-down—without implying a universal winner?

## Run

From the repository root:

```sh
python3 -m http.server 4173 --directory prototypes/generated-benchmark-report
```

Then open <http://localhost:4173/?variant=A>.

Use the floating arrows, keyboard left/right arrows, or `?variant=A|B|C`:

- **A — Decision memo:** workload recommendation first; evidence gate remains continuously visible.
- **B — Audit notebook:** publication validity and provenance first; conclusions come later.
- **C — Trade-off atlas:** routing and Pareto frontiers first; evidence is spatially linked.

The suite buttons are illustrative controls. They intentionally do not swap the fictional values in this throwaway prototype.
