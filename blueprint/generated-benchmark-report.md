# Prototype the generated benchmark report

**Status:** Final decision

**Decision date:** 2026-07-12

**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)

**Ticket:** [Prototype the generated benchmark report](https://github.com/MihaiA24/model-benchmarking/issues/22)

**Prototype:** [`prototypes/generated-benchmark-report/`](../prototypes/generated-benchmark-report/README.md)

## Accepted decisions

### Primary report hierarchy

Use the prototype's **Variant A — Decision memo** as the report's primary hierarchy:

1. orient the reader to the exact Suite visibility, Workload Family, model profile, worker profile, and compatible version stratum;
2. show raw planned, started, analysis-eligible, invalid, replaced, and complete-block denominators before or continuously beside any outcome claim;
3. lead the decision surface with the supported result for each Workload Family, including an explicit **no unique winner** state rather than a universal leaderboard;
4. lead each workload detail with paired strict-`task_success` effects, 95% uncertainty, the predeclared worthwhile margin, multiplicity-aware claim state, and matched denominator;
5. follow quality with nondominated cost, elapsed-time, resource, and limit tradeoffs; and
6. preserve drill-down from every aggregate to Scenario, Matched Block, Planned Trial Cell, effective Trial Attempt Record, sealed Result Bundle, and Artifact Descriptors.

Adopt two elements from the other prototype variants as subordinate views rather than competing report shells:

- Variant B's publication gate and provenance trace become evidence and reproducibility drill-downs.
- Variant C's Pareto atlas becomes a secondary workload tradeoff view after the paired quality result.

This hierarchy is workload-first, not leaderboard-first. It supports an organizational routing decision without allowing cost or visual rank to compensate for unsupported quality.

### Public and Private Suite navigation

Generate one sealed internal report with sibling top-level **Public Suite** and **Private Suite** views. Default to the Public Suite, retain the selected Suite visibility in every heading and link, and show a compact side-by-side robustness summary within each Workload Family. The summary compares claim states and effect direction without pooling observations, averaging scores, or hiding disagreements between Suites.

Generate any releasable report as a separately sealed derivative of the same report structure. It may expose only disclosure-approved Private Suite aggregates and must omit private Scenario identities, Trial drill-down, Result Bundle locators, and other access-controlled evidence. A withheld private detail is labelled as withheld rather than missing. The internal derivative retains access-controlled drill-down for both Suites.

Every statistic and chart belongs to exactly one Suite visibility stratum. Switching Suite views changes the evidence surface; it never changes weights inside a combined score because no such score exists.

### Static evidence drill-down

Generate the report as a self-contained, versioned static site with immutable relative links and no live database dependency. Use this typed drill-down path:

> Report → Workload Family → Scenario → Matched Block → Planned Trial Cell → effective Trial Attempt → Result Bundle manifest → disclosure-safe Artifact

Every hop displays its typed identity, applicable content digest, disposition or claim state, denominator, replacement or amendment lineage, and access state. Workload and Scenario aggregates link to their exact contributing blocks and effective attempts rather than to a mutable query. Trial pages preserve original and effective records when a replacement or amendment exists.

Artifact pages resolve the canonical bundle-relative path and digest, then expose bytes only when the selected report derivative is authorized to include them. `withheld_from_derivative`, `quarantined`, `removed_by_redaction`, `not_produced`, and other accepted availability states remain explicit terminal views rather than broken links or placeholder files. The static report never embeds access-controlled, quarantined, or unredacted bytes.

Seal the complete site as one report derivative. Its manifest inventories every generated page and included artifact by relative path, byte length, media type, and SHA-256 digest so the site can be copied, archived, and verified without changing link identity.

### Claim emphasis and neutral ordering

Use one fixed neutral Harness order throughout navigation, filters, tables, legends, and repeated charts. Record that order in the analysis manifest. Do not reorder Harnesses by observed score, cost, latency, or a selected filter, because moving the first position creates an implicit rank even when intervals overlap.

Do not use medals, podiums, winner colors, an overall rank, or a weighted universal score. A Workload Family may headline one Harness only when it satisfies the accepted **supported strongest** rule: supported superiority to both alternatives on strict `task_success`, no supported material regression harm, and valid common-support and integrity evidence. The headline always names the Workload Family, Suite visibility, and exact model stratum to which the claim applies.

Apply this headline precedence before any ranking: `unsupported comparison` when compatibility, qualification, integrity, or completeness cannot support the claim; otherwise the accepted `supported strongest` headline when its full rule passes; otherwise **no unique winner**. Unsupported evidence is removed from routing and never softened into an ordinary no-winner state. `inconclusive` and `supported practically equivalent` remain first-class neutral states rather than visually downgraded losses.

The initial Suite contract defines no quality non-inferiority or minimum-quality rule for operational routing. Therefore v1 reports cost, elapsed-time, resource, and Pareto evidence descriptively but emits no cheaper/faster routing preference. A later Suite Release may enable such routing only by predeclaring the exact quality gate and passing compatibility/versioning review; report code cannot invent one.

### Required page hierarchy

The accepted static report therefore contains:

1. a report landing page with derivative provenance, publication gate, frozen stratum controls, and one workload-routing summary per Suite view;
2. one Workload Family view per compatible Suite, model, worker, and version stratum, leading with paired strict-success effects and then partial-quality, probability-of-improvement, performance-profile, and operational/Pareto views;
3. a compact Public/Private robustness comparison that never pools the Suites;
4. disposition, denominator, sensitivity, analysis-method, and report-provenance appendices; and
5. the typed static evidence pages from Scenario through disclosure-safe Artifact.

The generated site is the inspectable presentation of a frozen analysis; it is not an exploratory dashboard that can silently redefine strata, weights, margins, exclusions, or estimands.

## Constraints carried from accepted dependencies

- Public and Private Suite evidence and exact model profiles remain separate Analysis Strata and are never silently pooled.
- The report consumes the effective append-only Run Ledger view; every aggregate is report-only and cannot overwrite canonical Trial evidence.
- A sealed report derivative records its input ledger and bundle-set digest, analysis-manifest identity and digest, analysis code and environment identity, bootstrap seed and resample count or exact-enumeration identity, deterministic generation epoch, and formula or column provenance. The generation epoch is a sealed input fixed before rendering and included in canonical bytes so repeated builds are byte-identical; actual publication time belongs to a separate append-only report-registry event outside the reproducible payload digest.
- Repetition counts, worthwhile effects, and precision targets remain owned by [Set repetition counts and precision targets](https://github.com/MihaiA24/model-benchmarking/issues/26); the report renders their frozen values without choosing them.
- Compatibility across Suite and verifier versions remains owned by [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23); the report fails closed rather than pooling strata without an accepted compatibility mapping.

## Decision completeness

The prototype resolves the static report structure, visual hierarchy, Suite navigation, claim emphasis, operational-tradeoff placement, and immutable evidence drill-down required by this ticket. It reuses the accepted scoring and Run Ledger semantics without choosing repetition counts, practical margins, Suite compatibility, or report-generator architecture for their downstream owners.
