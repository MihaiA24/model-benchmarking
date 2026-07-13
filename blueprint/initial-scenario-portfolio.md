# Select the initial scenario portfolio

**Status:** Accepted decision record — portfolio frozen for qualification
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)
**Ticket:** [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20)

## Accepted decisions

### Workload taxonomy

Assign every Scenario exactly one primary Workload Family from this closed set:

1. **Defect diagnosis and repair** — locate and correct a seeded behavioral defect in an existing Evaluated Repository, then preserve applicable regressions.
2. **Bounded feature implementation** — add observable behavior integrated into an existing Evaluated Repository. This family may include creating a new component, module, or pipeline when integration with the repository is part of the work.
3. **Test generation and hardening** — add meaningful executable tests for existing behavior, including relevant edge cases and regression protection, without changing production behavior except where minimal testability seams are explicitly allowed.
4. **Repository evolution** — perform a bounded dependency, framework, API, schema, or configuration migration while preserving declared behavior and compatibility.

The primary family identifies the professional change being requested, not the verifier technique or the files touched. Secondary descriptive tags may support portfolio review, but a Scenario is counted in only one Workload Family so workload strata and equal-scenario weighting remain unambiguous.

Do not create a separate greenfield family for the initial benchmark. Isolated creation exercises model coding more than autonomous repository navigation; repository-integrated creation belongs to Bounded feature implementation. Repository evolution is retained because it exercises cross-file navigation, compatibility reasoning, and iterative build/test repair that can distinguish Harness behavior.

### Portfolio size and suite balance

The Initial Scenario Portfolio contains **24 independently authored Scenarios**:

- 12 Public Suite Scenarios;
- 12 Private Suite Scenarios; and
- within each Suite, exactly one Scenario for every cell in the `3 ecosystems × 4 Workload Families` matrix.

The three ecosystems are Angular/TypeScript frontend, Spring Boot/Java backend, and Python data engineering. Each Suite therefore contains three Scenarios per Workload Family and four Scenarios per ecosystem. Public and Private Suite Scenarios must be substantively distinct; they may not be disclosed and hidden variants of the same brief, seed, expected behavior, or Reference Solution.

This is the minimum complete matrix that permits separately reported public and private fixed-suite workload comparisons without making a workload depend on only one or two Scenarios. Three Scenarios per workload remains insufficient for a strong scenario-population generalization claim, so the initial benchmark reports only the accepted fixed-suite estimand as canonical and labels any scenario-generalization analysis exploratory.

### Difficulty composition

Use two portfolio-balancing bands, **Standard** and **Challenging**. In each Suite, every Workload Family contains two Standard Scenarios and one Challenging Scenario, producing eight Standard and four Challenging Scenarios per Suite. Rotate the Challenging cells across ecosystems between the Public and Private Suites so no ecosystem is systematically assigned the harder work.

Freeze the Challenging cells as follows; every unlisted cell is Standard:

| Suite | Defect diagnosis and repair | Bounded feature implementation | Test generation and hardening | Repository evolution |
| --- | --- | --- | --- | --- |
| Public | Angular | Spring Boot | Python data engineering | Angular |
| Private | Spring Boot | Python data engineering | Angular | Spring Boot |

Each Workload Family changes ecosystem between Suites. Across the eight Challenging cells, Angular and Spring Boot each receive three and Python data engineering receives two, so the unavoidable remainder from distributing eight cells across three ecosystems does not systematically burden one Suite.

Classify the band before measured Harness Trials from the investigation depth, change surface, cross-layer coordination, and expected build/test feedback cycles required by the Scenario. Do not use observed benchmark Harness success to assign or revise the band. Difficulty is a portfolio descriptor, not a primary Analysis Stratum.

This two-band policy is project-owned, not derived from Terminal-Bench 2.1. [The primary-source comparison](../research/terminal-bench-2.1-methodology.md) found that Terminal-Bench stores author-facing `easy`/`medium`/`hard` metadata and human time estimates, while its paper separately reports post-hoc empirical difficulty from model pass rates. Retain human estimates as review evidence where useful, but do not import outcome-derived difficulty labels into this predeclared portfolio.

Exclude both trivial tasks that reveal the relevant location or implementation and open-ended tasks that cannot be bounded under `standard-v1`. Every selected Scenario must remain professionally plausible, independently verifiable, and demonstrably solvable through its Reference Solution and qualification workflow.

### Source repositories and confidentiality

Build Public Suite Scenarios from pinned, permissively licensed open-source repositories whose complete Scenario Packages may be released. Build Private Suite Scenarios from distinct permissively licensed open-source snapshots or clean-room representative repositories, while keeping their briefs, seeds, verifiers, solutions, and package identities access controlled until release or retirement.

Do not place confidential company source, production data, credentials, personal data, or non-redistributable assets in either Suite. Harness-controlled model requests may transmit repository content to the external provider, so `private` means undisclosed benchmark material rather than proprietary production source.

Public and Private Suite Scenarios must not share an Evaluated Repository lineage. Within one Suite, use at most two Scenarios from the same repository lineage and at most one from that lineage in any Workload Family. This prevents Spring Petclinic, RealWorld, Chinook, or another familiar source from dominating a Suite while permitting bounded reuse of an expensive qualified baseline.

### Portfolio eligibility gates

Use this closed pre-release state flow for every frozen portfolio cell: `authoring_target` or `private_slot` → `candidate` → `package_qualified` → `roster_selected` → `suite_sealed`. A rejected candidate becomes `rejected` with durable evidence and may be replaced only by another candidate for the same ecosystem × Workload Family × difficulty cell. No target, slot, candidate, or merely qualified package is a released Scenario until the Suite Release seals it.

A candidate may become `package_qualified` and enter the selected roster only when all of these conditions hold:

- it fills one required ecosystem-by-Workload-Family cell and satisfies the repository-lineage limits;
- its Developer Brief states observable professional behavior without identifying the fix location or prescribing an implementation;
- hidden acceptance and regression Check Groups deterministically verify behavior rather than treating compilation or build success as sufficient;
- the unchanged Scenario Baseline fails at least one required acceptance group while passing every applicable regression group;
- the Reference Solution produces the same successful score vector twice in fresh verifier environments;
- its declared capabilities fit the common `standard-v1` capability set required of all three Harness Stock Profiles; exact Harness, adapter, Provider Route, model, Execution Profile, and Worker Profile combinations qualify separately through experiment-owned Qualification Bundles before Planned Trial Cells become eligible;
- measured execution requires no download, mutable external service, or Harness-specific tool; and
- an independent reviewer confirms professional realism, brief/verifier alignment, implementation neutrality, licensing, bounded scope, and absence of answer leakage.

Exclude token-level or explicitly located repairs, isolated utility exercises without repository integration, build-only verification, subjective or documentation-only deliverables, tasks dependent on live third-party behavior, tasks requiring unmatched Harness capabilities or budgets, and tasks whose verifier is materially vulnerable to hardcoding or test tampering.

These portfolio gates specialize rather than replace the previously accepted Scenario Package qualification workflow. A candidate must pass both sets of gates and retain a Package Qualification Record before Suite sealing. The Suite Release seals package qualification evidence but never experiment-varying Qualification Bundles.

### Contamination and disclosure

Publish the exact Public Suite Scenarios and their complete releasable Scenario Packages. For the Private Suite, publish only the frozen slot contracts: ecosystem, Workload Family, difficulty band, verifier shape, realism requirements, and repository-lineage limits. Keep the exact private repository refs, Developer Briefs, seeds, verifiers, Reference Solutions, and package identities in an access-controlled manifest.

Before measured Trials, seal the access-controlled **Private Roster Manifest** over the exact Private Scenario, Verifier, Score Contract, package-lock, and package-payload identities; hash those canonical bytes into the **Private Suite Commitment**; then seal the outer Private Suite Release manifest that references both identities. This prescribed inner-roster → commitment → outer-release order is non-circular. The commitment proves that the held-out portfolio was frozen before outcomes were observed without disclosing its contents; it does not make an undisclosed package reproducible by the public.

For every candidate, record observable exposure such as public issues, patches, tests, prior benchmark use, and answer-bearing documentation. Do not claim to know whether a model trained on an artifact. Canary strings may be added as provenance markers, but they are not evidence that contamination was prevented. Discovery that private material leaked or that public material exposes the answer triggers the invalidation and rotation policy owned by [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23).

The exposure review is adapted from established benchmark contamination checks. The held-out Private Suite boundary and pre-trial content-addressed commitment are project-original safeguards; Terminal-Bench 2.1 publishes all tasks and does not provide an equivalent private test set.

### Legacy Calibration Suite

Keep the historical pilot tasks without allowing them to affect the Initial Scenario Portfolio or its results. Exclude all 11 legacy tasks from the measured Public and Private Suites because their task and solution intent are already disclosed, most are implementation-revealing single-file exercises, and their historical evidence is not comparable with autonomous CLI Trials.

Migrate three representative ideas into a separate, non-measured **Legacy Calibration Suite**:

1. Spring PetValidator whitespace-name repair, to exercise deterministic seeding and hidden regression packaging;
2. Angular reading-time feature, to exercise replacement of build-only scoring with behavioral checks; and
3. Python sales-by-genre repair, to exercise hidden expected data and anti-hardcoding checks.

Use the same Harbor substrate, Scenario Package format, Harness adapters, isolation boundary, and verifier contract so these fixtures test the real benchmark path. Run them as smoke, authoring-example, adapter-regression, and diagnostic fixtures; one Trial per condition is normally sufficient. Do not include them in production matched blocks, workload scores, uncertainty analyses, Public/Private reports, or winner claims. Preserve the remaining legacy tasks as historical pilot records and migrate one only when it covers a concrete regression gap.

This ticket owns the strict non-pooling boundary. [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23) owns the Calibration Suite namespace and lifecycle, while [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) owns physical reuse of the common package, adapter, execution, and verifier machinery without a second runner.

### Synthetic-first data fixtures

Use deterministic Synthetic Data Fixtures for every measured Python data-engineering Scenario by default. Version the schema, generator implementation, seed, distributions, invariants, generated-data digest, and any declared scale parameters as Scenario Package inputs. Give the Harness one realistic agent-visible fixture and verify behavior against additional verifier-only generated fixtures with different seeds and relevant edge regimes such as nulls, duplicates, ties, skew, late records, and schema drift.

Do not place Chinook, Jaffle Shop, Palmer Penguins, production data, or another external dataset in the measured Initial Scenario Portfolio unless a concrete selected behavior cannot be represented faithfully with generated data and the external source, version, redistribution rights, integrity, and contamination boundary all pass independent qualification. Synthetic data is not permission to use toy distributions: each generator must encode and document the professional invariants that make the task representative.

For the Legacy Calibration Suite's sales-by-genre fixture, preserve the relational task concept but replace the current Chinook bytes with a deterministic schema-compatible generated dataset unless exact source and redistribution rights are independently proven. This keeps the legacy diagnostic while preventing unresolved dataset provenance from entering the common benchmark path.

### Selected Angular/TypeScript slice

Freeze these four Public Suite authoring targets, backed by the pinned evidence and verifier projections in [the Angular candidate note](../research/angular-scenario-candidates.md):

| Workload Family | Difficulty | Evaluated Repository lineage | Scenario concept |
| --- | --- | --- | --- |
| Defect diagnosis and repair | Challenging | RealWorld Angular | Diagnose and repair a seeded feed-route state identity regression. |
| Bounded feature implementation | Standard | RealWorld Angular | Protect unsaved article drafts during in-app navigation. |
| Test generation and hardening | Standard | Taiga UI | Add mutation-backed tests for numeric and bigint quantum normalization. |
| Repository evolution | Challenging | NgRx Platform | Complete the `withEffects` to `withEventHandlers` migration across the declared supported consumer forms. |

Freeze the corresponding Private Suite slots without disclosing their repository or task material:

| Workload Family | Difficulty | Private slot contract |
| --- | --- | --- |
| Defect diagnosis and repair | Standard | A bounded behavioral regression requiring repository navigation, deterministic hidden acceptance, and preserved regressions. |
| Bounded feature implementation | Standard | A small repository-integrated Angular behavior with deterministic hidden integration checks. |
| Test generation and hardening | Challenging | A materially under-protected behavior assessed through deterministic hidden adequacy checks with strict production-change boundaries. |
| Repository evolution | Standard | A bounded framework, dependency, API, or configuration migration with explicit compatibility outcomes. |

RealWorld Angular, Taiga UI, and NgRx Platform are forbidden Private Suite lineages. These Public targets remain subject to every accepted inclusion gate during Scenario Package authoring. A target that fails licensing, hermetic execution, difficulty, verifier, solvability, or common-profile qualification must be replaced in the same cell through the same independent review; implementation may not silently weaken the cell or substitute a different workload.

### Selected Python data-engineering slice

Freeze these four Public Suite authoring targets, backed by the pinned evidence and verifier projections in [the Python data-engineering candidate note](../research/python-data-scenario-candidates.md):

| Workload Family | Difficulty | Evaluated Repository lineage | Scenario concept |
| --- | --- | --- | --- |
| Defect diagnosis and repair | Standard | Kedro | Repair seeded dataset-factory precedence and interpolation behavior. |
| Bounded feature implementation | Standard | DVC | Add an opt-in `params diff` mode that reports parameter changes through a documented process status while preserving existing output modes. |
| Test generation and hardening | Challenging | Dagster | Add mutation-backed tests for multi-dimensional partition mapping boundaries and composition. |
| Repository evolution | Standard | DVC | Replace the ConfigObj-backed configuration codec while preserving declared configuration behavior. |

Freeze the corresponding Private Suite slots without disclosing their repository or task material:

| Workload Family | Difficulty | Private slot contract |
| --- | --- | --- |
| Defect diagnosis and repair | Standard | A bounded seeded data or pipeline behavior defect with deterministic hidden synthetic acceptance and preserved regressions. |
| Bounded feature implementation | Challenging | A repository-integrated data-engineering capability requiring coordinated changes across established boundaries and deterministic synthetic checks. |
| Test generation and hardening | Standard | Tests-only strengthening of existing data behavior with a bounded hidden adequacy check and strict production-change boundaries. |
| Repository evolution | Standard | A bounded dependency, API, schema, or configuration migration with behavioral verification beyond build success. |

Kedro, DVC, and Dagster are forbidden Private Suite lineages. Every measured Python Scenario uses the accepted Synthetic Data Fixture contract. The DVC configuration migration is the highest-risk authoring target: replace it in the same cell if its compatibility corpus exceeds Standard difficulty or cannot be verified hermetically. All four targets otherwise follow the same mandatory replacement rule as the Angular slice.

### Selected Spring Boot/Java slice

Freeze these four Public Suite authoring targets, backed by the pinned evidence and verifier projections in [the Spring Boot/Java candidate note](../research/spring-scenario-candidates.md):

| Workload Family | Difficulty | Evaluated Repository lineage | Scenario concept |
| --- | --- | --- | --- |
| Defect diagnosis and repair | Standard | Spring Data Examples | Repair a seeded selective-update transaction-boundary defect that can commit an orphan child after optimistic-lock rejection. |
| Bounded feature implementation | Challenging | Spring Petclinic | Add a clinic-wide upcoming-visits schedule with inclusive date filtering, pagination, stable ordering, and owner/pet context. |
| Test generation and hardening | Standard | Spring Modulith | Add mutation-backed passage-of-time tests across locale week-years, shifted quarters, leap dates, and time-zone boundaries. |
| Repository evolution | Standard | Spring Boot RealWorld | Replace deprecated adapter-based Spring Security configuration while preserving JWT, CORS, stateless-session, and route-authorization behavior. |

Freeze these non-disclosing Private Suite slot contracts; exact package material belongs only in the access-controlled manifest and subsequent Private Suite Commitment:

| Workload Family | Difficulty | Private slot contract |
| --- | --- | --- |
| Defect diagnosis and repair | Challenging | A seeded cross-layer Spring behavior defect with deterministic hidden acceptance and preserved regressions. |
| Bounded feature implementation | Standard | A small repository-integrated Spring behavior with deterministic persistence, API, or MVC acceptance beyond build success. |
| Test generation and hardening | Standard | Tests-only strengthening of existing behavior with a bounded hidden adequacy check and strict production-change boundaries. |
| Repository evolution | Challenging | A bounded framework, dependency, schema, API, or configuration migration with explicit compatibility outcomes and offline behavioral verification. |

Spring Data Examples, Spring Petclinic, Spring Modulith, and Spring Boot RealWorld are forbidden Private Suite lineages. The Petclinic feature and Security migration are the highest-risk authoring targets: replace either in the same cell if it fails difficulty, hermeticity, or repository-reasoning qualification. All four targets otherwise follow the same mandatory replacement rule as the Angular slice.

### Supported claim classes and exclusions

After every Scenario Package passes qualification and the benchmark is executed under a content-addressed Suite Version and declared execution profile, the Initial Scenario Portfolio may support:

- relative Harness/model performance within that Suite Version and execution profile;
- separately reported results by ecosystem, Workload Family, predeclared difficulty band, and Public or Private Suite;
- the accepted paired fixed-suite estimands and uncertainty summaries;
- valid-completion rate, measured cost, and measured latency under the declared controls; and
- evidence for an organizational model-routing decision under the tested conditions.

The portfolio does **not** support a universal “best coding model”; claims about model training data or absence of contamination; general production safety, security, maintainability, or developer-productivity claims; extrapolation beyond the tested repositories, workloads, tools, capabilities, and resource profile; or use of canary strings as proof that leakage did not occur. Scenario-population generalization remains exploratory because each Workload Family contains only three Scenarios per Suite.

### Portfolio and Trial freeze boundary

Apply three explicit boundaries:

1. **Portfolio freeze — this decision.** Freeze the 24-cell matrix, ecosystem/Workload-Family/difficulty assignments, 12 Public Suite authoring targets, 12 non-disclosing Private Suite slot contracts, and the accepted disclosure, lineage, contamination, eligibility, qualification, and supported-claim rules.
2. **Qualification window — before measured Trials.** A Public target may be replaced only when it fails licensing, hermeticity, difficulty, verifier, solvability, common-profile, or independent-review qualification. The replacement must occupy the same ecosystem/Workload-Family/difficulty cell, pass the same review, and preserve a durable rejection record. Exact Private Suite Scenarios are selected and qualified inside the access-controlled manifest during this window. No replacement may silently weaken a cell or convert it to another workload.
3. **Trial freeze — before the first measured Trial.** Freeze the exact content-addressed Public Scenario Packages, access-controlled Private manifest and package digests, Developer Briefs, seeds, verifiers, repository snapshots, runtime images, and applicable policy manifests. Publish the Private Suite Commitment before invoking any measured model.

After the first measured Trial begins, do not edit, swap, or reclassify a Scenario Package in place. A correction, leakage response, or portfolio rotation creates a new Suite Version under [Define suite versioning and refresh policy](https://github.com/MihaiA24/model-benchmarking/issues/23); results from different Suite Versions are not silently pooled.
